"""
This is a base lightning module that can be used to train a model.
The benefit of this abstraction is that all the logic outside of model definition can be reused for different models.
"""
import inspect
from abc import ABC
from typing import Any, Dict, Optional

import torch
from lightning import LightningModule
from lightning.pytorch.utilities import grad_norm

from lits import utils
from lits.utils.utils import plot_tensor

# Get module-level logger
log = utils.get_pylogger(__name__)


class BaseLits(LightningModule, ABC):
    def __init__(self):
        super().__init__()

    def update_data_statistics(self, data_statistics: Optional[dict] = None) -> None:
        """
        Register mel_mean and mel_std as buffers for normalization.
        If data_statistics is None, use default values.
        """
        if data_statistics is None:
            data_statistics = {
                "mel_mean": 0.0,
                "mel_std": 1.0,
            }
        self.register_buffer("mel_mean", torch.tensor(data_statistics["mel_mean"]))
        self.register_buffer("mel_std", torch.tensor(data_statistics["mel_std"]))

    def configure_optimizers(self) -> Any:
        """
        Configure optimizer and learning rate scheduler for training.
        Ensures compatibility with checkpoint resume and Lightning's requirements.
        """
        optimizer = self.hparams.optimizer(params=self.parameters())
        if self.hparams.scheduler not in (None, {}):
            # 从scheduler中提取lightning_args，避免传递给scheduler构造函数
            lightning_args = getattr(self.hparams.scheduler, 'lightning_args', {})
            
            # 创建scheduler时排除lightning_args
            scheduler_kwargs = {}
            if hasattr(self.hparams.scheduler, 'func'):
                # 处理functools.partial对象
                scheduler_func = self.hparams.scheduler.func
                scheduler_kwargs = dict(self.hparams.scheduler.keywords)
                # 移除lightning_args
                scheduler_kwargs.pop('lightning_args', None)
            else:
                # 直接使用scheduler
                scheduler_func = self.hparams.scheduler
            
            # 添加optimizer参数
            scheduler_kwargs['optimizer'] = optimizer
            
            # 处理last_epoch参数
            if 'last_epoch' in scheduler_kwargs:
                if hasattr(self, "ckpt_loaded_epoch"):
                    scheduler_kwargs['last_epoch'] = self.ckpt_loaded_epoch - 1
                else:
                    scheduler_kwargs['last_epoch'] = -1
            
            # 创建scheduler实例
            scheduler = scheduler_func(**scheduler_kwargs)
            
            return {
                "optimizer": optimizer,
                "lr_scheduler": {
                    "scheduler": scheduler,
                    "interval": lightning_args.get("interval", "epoch"),
                    "frequency": lightning_args.get("frequency", 1),
                    "name": "learning_rate",
                },
            }
        
        return {"optimizer": optimizer}

    def get_losses(self, batch: dict) -> dict:
        """
        Compute all loss components for a batch.
        Returns a dict with dur_loss, prior_loss, diff_loss.
        """
        x, x_lengths = batch["x"], batch["x_lengths"]
        y, y_lengths = batch["y"], batch["y_lengths"]
        spks = batch["spks"]
        dur_loss, prior_loss, diff_loss, *_ = self(
            x=x,
            x_lengths=x_lengths,
            y=y,
            y_lengths=y_lengths,
            spks=spks,
            out_size=self.out_size,
            durations=batch["durations"],
        )
        return {
            "dur_loss": dur_loss,
            "prior_loss": prior_loss,
            "diff_loss": diff_loss,
        }

    def on_load_checkpoint(self, checkpoint: Dict[str, Any]) -> None:
        """
        Restore epoch information from checkpoint for scheduler compatibility.
        """
        self.ckpt_loaded_epoch = checkpoint["epoch"]  # pylint: disable=attribute-defined-outside-init

    def training_step(self, batch: Any, batch_idx: int) -> dict:
        """
        Perform a training step, log all loss components, and return total loss.
        """
        loss_dict = self.get_losses(batch)
        self.log(
            "step",
            float(self.global_step),
            on_step=True,
            prog_bar=True,
            logger=True,
            sync_dist=True,
        )
        self.log(
            "sub_loss/train_dur_loss",
            loss_dict["dur_loss"],
            on_step=True,
            on_epoch=True,
            logger=True,
            sync_dist=True,
        )
        self.log(
            "sub_loss/train_prior_loss",
            loss_dict["prior_loss"],
            on_step=True,
            on_epoch=True,
            logger=True,
            sync_dist=True,
        )
        self.log(
            "sub_loss/train_diff_loss",
            loss_dict["diff_loss"],
            on_step=True,
            on_epoch=True,
            logger=True,
            sync_dist=True,
        )
        total_loss = (
            loss_dict["dur_loss"] +
            loss_dict["prior_loss"] +
            loss_dict["diff_loss"]
        )
        self.log(
            "loss/train",
            total_loss,
            on_step=True,
            on_epoch=True,
            logger=True,
            prog_bar=True,
            sync_dist=True,
        )

        # 记录当前学习率（lr）
        if self.trainer is not None and hasattr(self.trainer, "optimizers") and self.trainer.optimizers:
            current_lr = self.trainer.optimizers[0].param_groups[0]["lr"]
            self.log(
                "learning_rate/lr",
                current_lr,
                on_step=True,
                on_epoch=True,
                prog_bar=True,
                logger=True,
                sync_dist=True,
            )
        else:
            log.warning("No optimizer found in trainer")

        return {"loss": total_loss, "log": loss_dict}

    def validation_step(self, batch: Any, batch_idx: int) -> float:
        """
        Perform a validation step, log all loss components, and return total loss.
        """
        loss_dict = self.get_losses(batch)
        self.log(
            "sub_loss/val_dur_loss",
            loss_dict["dur_loss"],
            on_step=True,
            on_epoch=True,
            logger=True,
            sync_dist=True,
        )
        self.log(
            "sub_loss/val_prior_loss",
            loss_dict["prior_loss"],
            on_step=True,
            on_epoch=True,
            logger=True,
            sync_dist=True,
        )
        self.log(
            "sub_loss/val_diff_loss",
            loss_dict["diff_loss"],
            on_step=True,
            on_epoch=True,
            logger=True,
            sync_dist=True,
        )
        total_loss = (
            loss_dict["dur_loss"] +
            loss_dict["prior_loss"] +
            loss_dict["diff_loss"]
        )
        self.log(
            "loss/val",
            total_loss,
            on_step=True,
            on_epoch=True,
            logger=True,
            prog_bar=True,
            sync_dist=True,
        )
        return total_loss

    def on_validation_end(self) -> None:
        """
        Visualize original and generated samples at validation end.
        Only runs on global rank zero.
        """
        if self.trainer.is_global_zero:
            one_batch = next(iter(self.trainer.val_dataloaders))
            n_vis = min(2, one_batch["y"].shape[0])
            if self.current_epoch == 0:
                log.debug("Plotting original samples")
                for i in range(n_vis):
                    y = one_batch["y"][i].unsqueeze(0).to(self.device)
                    self.logger.experiment.add_image(
                        f"original/{i}",
                        plot_tensor(y.squeeze().cpu()),
                        self.current_epoch,
                        dataformats="HWC",
                    )
            log.debug("Synthesising...")
            for i in range(n_vis):
                x = one_batch["x"][i].unsqueeze(0).to(self.device)
                x_lengths = one_batch["x_lengths"][i].unsqueeze(0).to(self.device)
                spks = one_batch["spks"][i].unsqueeze(0).to(self.device) if one_batch["spks"] is not None else None
                output = self.synthesise(x[:, :x_lengths], x_lengths, n_timesteps=10, spks=spks)
                y_enc, y_dec = output["encoder_outputs"], output["decoder_outputs"]
                attn = output["attn"]
                self.logger.experiment.add_image(
                    f"generated_enc/{i}",
                    plot_tensor(y_enc.squeeze().cpu()),
                    self.current_epoch,
                    dataformats="HWC",
                )
                self.logger.experiment.add_image(
                    f"generated_dec/{i}",
                    plot_tensor(y_dec.squeeze().cpu()),
                    self.current_epoch,
                    dataformats="HWC",
                )
                self.logger.experiment.add_image(
                    f"alignment/{i}",
                    plot_tensor(attn.squeeze().cpu()),
                    self.current_epoch,
                    dataformats="HWC",
                )

    def on_before_optimizer_step(self, optimizer: Any) -> None:
        """
        Log gradient norm for all parameters before optimizer step.
        """
        self.log_dict({f"grad_norm/{k}": v for k, v in grad_norm(self, norm_type=2).items()})
