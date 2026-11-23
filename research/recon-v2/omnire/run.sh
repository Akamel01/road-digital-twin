#!/bin/sh
# usage: run.sh NAME ITERS [extra omegaconf overrides...]
NAME=$1; IT=$2; shift 2
cd /data/recon-v2/omnire/drivestudio
export RV2_SPLIT=/data/recon-v2/omnire/split239.json PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True PYTHONUNBUFFERED=1
exec ../venv/bin/python tools/train.py --config_file configs/rv2_omnire.yaml --output_root /data/recon-v2/omnire/runs --project rv2 --run_name $NAME \
  data.data_root=data/nuscenes/processed_10Hz/trainval data.scene_idx=239 data.start_timestep=0 data.end_timestep=-1 \
  data.pixel_source.load_smpl=False trainer.optim.num_iters=$IT "$@"
