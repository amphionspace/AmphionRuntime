#!/bin/bash

work_dir=$(pwd)
export PYTHONPATH="$work_dir:$PYTHONPATH"

export NCCL_P2P_DISABLE=1
export NCCL_IB_DISABLE=1
export HYDRA_FULL_ERROR=1
export NCCL_DEBUG=INFO
export NCCL_SHM_DISABLE=1

PYTHONWARNINGS="ignore" python lits/train.py \
    experiment="en-zh_pinyin" \
    trainer.devices=[0,1,2,3,4,5,6]
