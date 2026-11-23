import sys

from datasets.nuscenes.nuscenes_preprocess import NuScenesProcessor

ids = [int(x) for x in sys.argv[1:]]
p = NuScenesProcessor(load_dir="data/nuscenes/raw", save_dir="data/nuscenes/processed", split="v1.0-trainval",
                      interpolate_N=4, process_keys=["images", "lidar", "calib", "dynamic_masks", "objects"], process_id_list=ids, workers=1)
for i in ids:
    p.convert_one_interpolated(i)
print("Finished", ids)
