import asyncio
import logging
import os
import traceback

from lightning import Trainer
from lightning.pytorch.loggers import CSVLogger

from nebula.config.config import TRAINING_LOGGER, Config
from nebula.core.eventmanager import EventManager
from nebula.core.nebulaevents import TrustNodeAddedEvent, RepresantativesUpdateEvent, PromotionEvent, \
    NewRepresentativeEvent
from nebula.core.network.communications import CommunicationsManager
from nebula.core.utils.nebulalogger_tensorboard import NebulaTensorBoardLogger
from nebula.core.validator.validator import Validator

logging_training = logging.getLogger(TRAINING_LOGGER)


class SDFLAccuracyValidator(Validator):
    """
    SDFLAccuracyValidator validates the model by comparing the accuracy before and after the aggregation.
    This implementation is designed for SDFL scenarios, only trustworthy nodes will validate.
    Follower nodes expect a validation decision from the trustworthy nodes.
    """

    def __init__(self, config: Config, model, datamodule, margin_of_error=0.1):
        self._logger = None
        self.datamodule = datamodule
        self.model = model
        self.config = config
        self._trainer = None
        self.accuracy = {}
        self.margin_of_error = margin_of_error
        self.epochs = self.config.participant["training_args"]["epochs"]
        self.experiment_name = self.config.participant["scenario_args"]["name"]
        self.idx = self.config.participant["device_args"]["idx"]
        self.log_dir = os.path.join(self.config.participant["tracking_args"]["log_dir"], self.experiment_name)
        self._lock = asyncio.Lock()

        self.valid = None
        self.valid_event = asyncio.Event()
        self.received_votes = {}
        self.received_votes_event = asyncio.Event()
        self.ip = config.participant["network_args"]["ip"]
        self.port = config.participant["network_args"]["port"]

        self.trust_nodes: set[str] = set(config.participant["sdfl_args"]["trust_nodes"])
        self.represented = config.participant["sdfl_args"]["represented_nodes"]
        self.representative = config.participant["sdfl_args"]["representative"]

        self.initial_round = -1

    @property
    def addr(self):
        return f"{self.ip}:{self.port}"

    async def subscribe_to_events(self):
        em: EventManager = EventManager.get_instance()
        await em.subscribe_node_event(TrustNodeAddedEvent, self._add_node)
        await em.subscribe_node_event(RepresantativesUpdateEvent, self._update_reps)
        await em.subscribe_node_event(PromotionEvent, self._activate_validator)
        await em.subscribe_node_event(NewRepresentativeEvent, self._update_rep)
        await em.subscribe(("validation", "vote"), self._vote_update)
        await em.subscribe(("validation", "info"), self._validation_info)

    async def _vote_update(self, source, message):
        tested = message.tested
        valid = message.valid
        async with self._lock:
            self.received_votes[source] = (tested, valid)
            if len(self.received_votes) == len(self.trust_nodes):
                self.received_votes_event.set()

    async def _update_rep(self, re: NewRepresentativeEvent):
        r = await re.get_event_data()
        async with self._lock:
            self.representative = r

    async def _validation_info(self, source, message):
        if source != self.representative:
            return

        async with self._lock:
            self.valid = message.valid
            self.valid_event.set()

    async def _add_node(self, te: TrustNodeAddedEvent):
        nodes = await te.get_event_data()
        async with self._lock:
            if self.addr in self.received_votes:
                await self._send_votes(self.received_votes[self.addr], nodes)
            self.trust_nodes.update(nodes)

    async def _update_reps(self, te: RepresantativesUpdateEvent):
        reps = await te.get_event_data()
        async with self._lock:
            self.represented = reps

    async def _activate_validator(self, te: PromotionEvent):
        reps, trusted, round_num = await te.get_event_data()
        async with self._lock:
            self.represented = reps
            self.trust_nodes = trusted
            self.initial_round = round_num

    def create_logger(self):
        if self.config.participant["tracking_args"]["local_tracking"] == "csv":
            nebulalogger = CSVLogger(f"{self.log_dir}", name="metrics", version=f"participant_{self.idx}")
        elif self.config.participant["tracking_args"]["local_tracking"] == "basic":
            logger_config = None
            if self._logger is not None:
                logger_config = self._logger.get_logger_config()
            nebulalogger = NebulaTensorBoardLogger(
                self.config.participant["scenario_args"]["start_time"],
                f"{self.log_dir}",
                name="metrics",
                version=f"participant_{self.idx}",
                log_graph=False,
            )
            # Restore logger configuration
            nebulalogger.set_logger_config(logger_config)
        else:
            nebulalogger = None

        self._logger = nebulalogger

    def create_trainer(self):
        # Create a new trainer and logger for each round
        self.create_logger()
        num_gpus = len(self.config.participant["device_args"]["gpu_id"])
        if self.config.participant["device_args"]["accelerator"] == "gpu" and num_gpus > 0:
            # Use all available GPUs
            if num_gpus > 1:
                gpu_index = [self.config.participant["device_args"]["idx"] % num_gpus]
            # Use the selected GPU
            else:
                gpu_index = self.config.participant["device_args"]["gpu_id"]
            logging_training.info(f"Creating trainer with accelerator GPU ({gpu_index})")
            self._trainer = Trainer(
                callbacks=[],
                max_epochs=self.epochs,
                accelerator="gpu",
                devices=gpu_index,
                logger=self._logger,
                enable_checkpointing=False,
                enable_model_summary=False,
                # deterministic=True
            )
        else:
            logging_training.info("Creating trainer with accelerator CPU")
            self._trainer = Trainer(
                callbacks=[],
                max_epochs=self.epochs,
                accelerator="cpu",
                devices="auto",
                logger=self._logger,
                enable_checkpointing=False,
                enable_model_summary=False,
                # deterministic=True
            )
        logging_training.info(f"Trainer strategy: {self._trainer.strategy}")

    def _test_sync(self):
        try:
            self._trainer.test(self.model, self.datamodule, verbose=False)
            metrics = self._trainer.callback_metrics

            # dataloader_idx_0 is the dataloader using the local dataset
            loss = metrics.get('val_loss/dataloader_idx_0', None).item()
            accuracy = metrics.get('val_accuracy/dataloader_idx_0', None).item()
            return loss, accuracy
        except Exception as e:
            logging_training.error(f"Error in _test_sync: {e}")
            tb = traceback.format_exc()
            logging_training.error(f"Traceback: {tb}")

            # If "raise", the exception will be managed by the main thread
            return None, None

    async def _await_decision(self):
        await self.valid_event.wait()
        self.valid_event.clear()
        return

    async def _await_voting(self, election_num):
        await self.received_votes_event.wait()

        async with self._lock:
            votes_to_process = self.received_votes
            self.received_votes = {}
            self.received_votes_event.clear()

        # First expect 70% accepts, reduce requirement by 10% each time it fails
        # After 5 fails percentage will be 0.0% and it will always accept
        initial_accept_percentage = 0.7
        current_accept_percentage = initial_accept_percentage - 0.1 * election_num

        accepts = 0
        total = 0
        for tested, valid in votes_to_process.values():
            if not tested:
                continue
            accepts += 1 if valid else 0
            total += 1

        if total > 0:
            accept_percentage = accepts / total
        else:
            accept_percentage = 1
        async with self._lock:
            self.valid = accept_percentage >= current_accept_percentage

    async def _send_decision(self):
        cm: CommunicationsManager = CommunicationsManager.get_instance()
        m = cm.create_message(message_type="validation", action="info", tested=True, valid=self.valid)
        for node in self.represented:
            if node == self.addr:
                continue
            await cm.send_message(node, m)

    async def _send_votes_to_all(self, vote):
        await self._send_votes(vote, self.trust_nodes)

    async def _send_votes(self, vote, nodes):
        tested = vote[0]
        valid = vote[1]
        cm: CommunicationsManager = CommunicationsManager.get_instance()
        m = cm.create_message(message_type="validation", action="vote", tested=tested, valid=valid)
        for node in nodes:
            if node == self.addr:
                continue
            await cm.send_message(node, m)

    async def _vote(self, params, round_num):
        try:
            self.create_trainer()
            logging.info(f"{'=' * 10} [Testing] Started (check training logs for progress) {'=' * 10}")
            self.model.load_state_dict(params)
            _, accuracy = await asyncio.to_thread(self._test_sync)
            logging.info(f"{'=' * 10} [Testing] Finished (check training logs for progress) {'=' * 10}")
            prev = round_num - 1
            async with (self._lock):
                prev_acc = self.accuracy.get(prev, -1)
                if prev_acc == -1:
                    vote = (False, False)
                    self.received_votes[self.addr] = vote
                elif prev_acc - self.margin_of_error <= accuracy:
                    vote = (True, True)
                    self.received_votes[self.addr] = vote
                else:
                    vote = (True, False)
                    self.received_votes[self.addr] = vote

                if len(self.received_votes) == len(self.trust_nodes):
                    self.received_votes_event.set()
                self.accuracy[round_num] = accuracy
            await self._send_votes_to_all(vote)

        except Exception as e:
            logging_training.error(f"Error testing model: {e}")
            logging_training.error(traceback.format_exc())
            async with self._lock:
                vote = (False, False)
                self.received_votes[self.addr] = vote
                if len(self.received_votes) == len(self.trust_nodes):
                    self.received_votes_event.set()
            await self._send_votes_to_all(vote)

    async def validate(self, params, round_num, election_num):
        if self.addr in self.trust_nodes and round_num >= self.initial_round:
            await self._vote(params, round_num)
            await self._await_voting(election_num)
            await self._send_decision()
        else:
            await self._await_decision()

        return self.valid
