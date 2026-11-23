#!/bin/sh
# usage: run.sh NAME ITERS [extra ns-train args...]; detached container rv2-splatad-NAME
NAME=$1; IT=$2; shift 2
mkdir -p /data/recon-v2/splatad/outputs
docker run -d --name rv2-splatad-$NAME --gpus all --shm-size=8g --memory=36g --ulimit nofile=65536:65536 \
  -e RV2_HOLDOUT=/rv2/holdout0297.json -e PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True -e PYTHONUNBUFFERED=1 \
  -v /data/nuscenes:/data/nuscenes:ro -v /data/recon-v2/splatad/neurad-studio:/workspace/neurad-studio \
  -v /data/recon-v2/splatad:/rv2 -v /data/recon-v2/splatad/outputs:/workspace/neurad-studio/outputs \
  rv2-neurad-studio ns-train splatad --experiment-name $NAME --vis tensorboard --max-num-iterations $IT \
  --steps-per-eval-all-images 1000000 --pipeline.model.mcmc-cap-max 1000000 --pipeline.model.max-num-seed-points 500000 "$@" \
  nuscenes-data --data /data/nuscenes --version v1.0-trainval --sequence 0297
