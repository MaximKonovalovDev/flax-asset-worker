# Hunyuan3D-2MV Colab Runbook (Roman Arena)

Use this when Colab MCP is unavailable or you want to run manually.

## Inputs
- Use the 4-view images here:
  `<repo>\AssetBoy\state\generated\hunyuan3d2.production\roman_arena_mv_refs\colab_128`
- Files needed: `front.jpg`, `back.jpg`, `left.jpg`, `right.jpg`

## Steps
1. Open a new Google Colab notebook and select GPU (T4 is fine).
2. Upload the 4 images into Colab (left sidebar > Files > Upload).
3. Run the cell below.
4. Download `/content/output/roman_arena_mv.glb`.

## Colab Cell
```python
import os, sys, subprocess, importlib.util
from pathlib import Path

# system deps
subprocess.check_call(["apt-get","update","-y"])
subprocess.check_call(["apt-get","install","-y","libgl1-mesa-glx","libglib2.0-0","xvfb"])

# repo
if not Path("cog-hunyuan3d-2mv").exists():
    subprocess.check_call(["git","clone","https://github.com/lucataco/cog-hunyuan3d-2mv.git"])
os.chdir("cog-hunyuan3d-2mv")

# python deps
pkgs = [
    ("ninja","ninja"),
    ("pybind11","pybind11"),
    ("diffusers","diffusers"),
    ("einops","einops"),
    ("opencv-python","cv2"),
    ("transformers","transformers"),
    ("omegaconf","omegaconf"),
    ("tqdm","tqdm"),
    ("trimesh","trimesh"),
    ("pymeshlab","pymeshlab"),
    ("pygltflib","pygltflib"),
    ("xatlas","xatlas"),
    ("accelerate","accelerate"),
    ("rembg","rembg"),
    ("onnxruntime","onnxruntime"),
    ("huggingface-hub","huggingface_hub"),
]
for pkg, mod in pkgs:
    if importlib.util.find_spec(mod) is None:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

if importlib.util.find_spec("cog") is None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "cog"])

# pget for weights
subprocess.check_call(["bash","-lc","curl -o /usr/local/bin/pget -L \"https://github.com/replicate/pget/releases/download/v0.8.2/pget_linux_x86_64\" && chmod +x /usr/local/bin/pget"])

# move images into /content/inputs
Path("/content/inputs").mkdir(parents=True, exist_ok=True)
for name in ["front.jpg","back.jpg","left.jpg","right.jpg"]:
    src = Path("/content") / name
    if src.exists():
        (Path("/content/inputs") / name).write_bytes(src.read_bytes())

# run predictor
import predict
pred = predict.Predictor()
pred.setup()

out = pred.predict(
    front_image="/content/inputs/front.jpg",
    back_image="/content/inputs/back.jpg",
    left_image="/content/inputs/left.jpg",
    right_image="/content/inputs/right.jpg",
    steps=25,
    guidance_scale=5.0,
    seed=0,
    octree_resolution=192,
    remove_background=True,
    num_chunks=120000,
    randomize_seed=False,
    target_face_num=20000,
    file_type="glb",
)

print("Output:", out)

Path("/content/output").mkdir(parents=True, exist_ok=True)
out_path = "/content/output/roman_arena_mv.glb"
Path(out_path).write_bytes(Path(str(out)).read_bytes())
print("Saved:", out_path)
```

## Notes
- If you want higher quality, use the 256x256 images in
  `<repo>\AssetBoy\state\generated\hunyuan3d2.production\roman_arena_mv_refs\colab_256`
- If Colab runs out of memory, reduce `num_chunks` to 80000.
