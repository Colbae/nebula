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
        self.round = -1
        self.config = config
        self._trainer = None
        self.accuracy = {}
        self.margin_of_error = margin_of_error
        self.epochs = self.config.participant["training_args"]["epochs"]
        self.experiment_name = self.config.participant["scenario_args"]["name"]
        self.idx = self.config.participant["device_args"]["idx"]
        self.log_dir = os.path.join(self.config.participant["tracking_args"]["log_dir"], self.experiment_name)
        self._lock = asyncio.Lock()

        self.represented = config.participant["sdfl_args"]["representated_nodes"]
        self.representative = config.participant["sdfl_args"]["representative"]
        self.valid = None
        self.valid_event = asyncio.Event()
        self.received_votes = []
        self.received_votes_event = asyncio.Event()
        self.ip = config.participant["network_args"]["ip"]
        self.port = config.participant["network_args"]["port"]

        trust = ["192.168.51.2:45001", "192.168.51.4:45003"]
        reper = f"{self.ip}:{self.port}"
        rep = None
        if config.participant["network_args"]["port"] == 45002:
            reper = "192.168.51.2:45001"
        elif config.participant["network_args"]["port"] == 45004:
            reper = "192.168.51.4:45003"
        if config.participant["network_args"]["port"] == 45001:
            rep = ["192.168.51.2:45001", "192.168.51.3:45002"]
        elif config.participant["network_args"]["port"] == 45003:
            rep = ["192.168.51.4:45003", "192.168.51.5:45004"]
        self.trust_nodes = trust  # config.participant["sdfl_args"]["trusted_nodes"]
        self.represented = rep
        self.representative = reper

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
        if source not in self.trust_nodes:
            return
        tested = message.tested
        valid = message.valid
        async with self._lock:
            self.received_votes.append((tested, valid))
            if len(self.received_votes) == len(self.trust_nodes):
                self.received_votes_event.set()

    async def _update_rep(self, re: NewRepresentativeEvent):
        r = re.get_event_data()
        async with self._lock:
            self.representative = r

    async def _validation_info(self, source, message):
        if source != self.representative:
            return

        async with self._lock:
            self.valid = message.valid
            self.valid_event.set()

    async def _add_node(self, te: TrustNodeAddedEvent):
        node = await te.get_event_data()
        async with self._lock:
            self.trust_nodes.append(node)

    async def _update_reps(self, te: RepresantativesUpdateEvent):
        reps = await te.get_event_data()
        async with self._lock:
            self.represented = reps

    async def _activate_validator(self, te: PromotionEvent):
        reps, trusted = await te.get_event_data()
        async with self._lock:
            self.represented = reps
            self.trust_nodes = trusted

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
            self._trainer.test(self.model, self.datamodule, verbose=True)
            metrics = self._trainer.callback_metrics
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

    async def _await_voting(self):
        await self.received_votes_event.wait()

        async with self._lock:
            votes_to_process = self.received_votes
            self.received_votes = []
            self.received_votes_event.clear()

        accepts = 0
        rejects = 0
        for tested, valid in votes_to_process:
            if not tested:
                continue
            accepts += 1 if valid else 0
            rejects += 0 if valid else 1

        async with self._lock:
            self.received_votes = []
            self.valid = accepts >= rejects

    async def _send_decision(self):
        cm: CommunicationsManager = CommunicationsManager.get_instance()
        m = cm.create_message(message_type="validation", action="info", tested=True, valid=self.valid)
        for node in self.represented:
            if node == self.addr:
                continue
            await cm.send_message(node, m)

    async def _send_vote(self, vote):
        tested = vote[0]
        valid = vote[1]
        cm: CommunicationsManager = CommunicationsManager.get_instance()
        m = cm.create_message(message_type="validation", action="vote", tested=tested, valid=valid)
        for node in self.trust_nodes:
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
            async with self._lock:
                if self.accuracy.get(prev, 0) - self.margin_of_error <= accuracy:
                    vote = (True, True)
                    self.received_votes.append(vote)
                else:
                    vote = (True, False)
                    self.received_votes.append(vote)

                if len(self.received_votes) == len(self.trust_nodes):
                    self.received_votes_event.set()
                self.accuracy[round_num] = accuracy
            await self._send_vote(vote)

        except Exception as e:
            logging_training.error(f"Error testing model: {e}")
            logging_training.error(traceback.format_exc())
            async with self._lock:
                vote = (False, False)
                self.received_votes.append(vote)
            await self._send_vote(vote)

    async def validate(self, params, round_num):
        if self.addr in self.trust_nodes:
            await self._vote(params, round_num)
            await self._await_voting()
            await self._send_decision()
        else:
            await self._await_decision()

        return self.valid
