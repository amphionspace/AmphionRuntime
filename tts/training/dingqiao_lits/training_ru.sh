#!/bin/bash

work_dir=$(pwd)
export PYTHONPATH="$work_dir:$PYTHONPATH"


PYTHONWARNINGS="ignore" python lits/train.py \
    experiment="0602_en-ru_arpa" \
    trainer.devices=[0,1,2,3] \
    trainer.precision=bf16-mixed \