"""Step 4 jobs for the Open Source (COLMAP + OpenMVS) and Hybrid (Agisoft cameras + OpenMVS) engines.

The heavy work happens in a local work folder (depth maps are ~36 MB per photo); only the result
(model, textures, CAM_<Object>.xml, engine_result.json) and the logs are copied into the object's
zz.COLMAP_OMVS folder. When the job ends, step 8 publishes the result into 01.CAM_Photos /
02.Geometry and Build Scene can run."""
import glob
import json
import os
import shutil
from datetime import datetime

from ..linker.checks import index_photos, pick_jpg
from ..metashape.photos import read_image_size
from ..project import jobs, paths
from . import colmap_xml, tools

# densify resolution level, refine on/off, texture resolution level
PRESETS = {"FAST": (2, False, 2), "NORMAL": (1, True, 1), "HIGH": (0, True, 0)}
MAX_EXHAUSTIVE = 300


def _openmvs_steps(work, preset, first_input):
    dens, refine, tex = PRESETS[preset]
    mvs = lambda t, *a: [tools.openmvs(t), "-w", work] + list(a)
    steps = [
        jobs.Step("Dense point cloud", mvs("DensifyPointCloud", "-i", first_input, "-o", "scene_dense.mvs",
                                           "--resolution-level", dens), weight=30),
        jobs.Step("Mesh", mvs("ReconstructMesh", "-i", "scene_dense.mvs", "-o", "scene_mesh.mvs"), weight=8),
    ]
    mesh = "scene_mesh.ply"
    if refine:
        steps.append(jobs.Step("Refine mesh", mvs("RefineMesh", "-i", "scene_dense.mvs", "-m", mesh,
                                                  "-o", "scene_refine.mvs", "--resolution-level", 2), weight=15))
        mesh = "scene_refine.ply"
    steps.append(jobs.Step("Texture", mvs("TextureMesh", "-i", "scene_dense.mvs", "-m", mesh,
                                          "-o", "scene_texture.mvs", "--export-type", "obj",
                                          "--resolution-level", tex), weight=10))
    return steps


def _collect_result(root, work, engine, cam_xml, undistorted, photos_dir):
    """Copy model + textures + XML + logs into zz.COLMAP_OMVS\\result and write engine_result.json."""
    found = paths.locate(root)
    res_dir = os.path.join(found["open"] or os.path.join(root, paths.SCAN, paths.OPEN), "result")
    logs = os.path.join(os.path.dirname(res_dir), "logs")
    os.makedirs(res_dir, exist_ok=True)
    os.makedirs(logs, exist_ok=True)
    obj = os.path.join(work, "scene_texture.obj")
    if not os.path.exists(obj):
        raise FileNotFoundError("TextureMesh wrote no scene_texture.obj")
    textures = sorted(glob.glob(os.path.join(work, "scene_texture*_map_Kd.*")))
    for f in [obj, os.path.join(work, "scene_texture.mtl"), cam_xml] + textures:
        if os.path.exists(f):
            shutil.copy2(f, os.path.join(res_dir, os.path.basename(f)))
    for lg in glob.glob(os.path.join(work, "*.log")):
        shutil.copy2(lg, os.path.join(logs, os.path.basename(lg)))
    result = {"engine": engine, "date": datetime.now().isoformat(timespec="seconds"),
              "cameras": os.path.basename(cam_xml), "model": "scene_texture.obj", "mtl": "scene_texture.mtl",
              "textures": [os.path.basename(t) for t in textures], "undistorted": undistorted,
              "photos": photos_dir, "axis": "Z_UP"}
    with open(os.path.join(res_dir, "engine_result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    return res_dir


def _photos(root):
    found = paths.locate(root)
    src = index_photos(found["source"], skip=(paths.ORIGINALS,))
    return {stem: pick_jpg(v) for stem, v in src.items()}


def opensource_job(root, preset="NORMAL", on_done=None):
    work = tools.work_dir(root, "OPENSOURCE")
    obj = paths.object_name(root)
    colmap = tools.colmap_exe()
    env = tools.colmap_env()
    db = os.path.join(work, "database.db")
    images = os.path.join(work, "images")
    sparse = os.path.join(work, "sparse")
    dense = os.path.join(work, "dense")
    photos = _photos(root)
    if len(photos) < 3:
        raise ValueError("Fewer than 3 photos in zz.Source_Photos (run Convert & Sort first)")

    def prepare(job):
        """Local copies grouped by photo size: one COLMAP camera per lens (single_camera_per_folder)."""
        for d in (sparse, dense):
            shutil.rmtree(d, ignore_errors=True)
        if os.path.exists(db):
            os.remove(db)
        os.makedirs(images, exist_ok=True)
        os.makedirs(sparse, exist_ok=True)
        wanted = set()
        for n, (stem, src) in enumerate(sorted(photos.items())):
            size = read_image_size(src) or (0, 0)
            group = os.path.join(images, f"lens_{size[0]}x{size[1]}")
            os.makedirs(group, exist_ok=True)
            dst = os.path.join(group, os.path.basename(src))
            wanted.add(os.path.normcase(dst))
            if not (os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src)):
                shutil.copy2(src, dst)
            job.step_pct = 100.0 * (n + 1) / len(photos)
        for d, _dirs, files in os.walk(images):          # photos removed since the last run
            for f in files:
                if os.path.normcase(os.path.join(d, f)) not in wanted:
                    os.remove(os.path.join(d, f))
        if len(photos) > MAX_EXHAUSTIVE:
            job.log(f"WARNING {len(photos)} photos: exhaustive matching will be slow")

    def pick_model(job):
        """The largest sparse model (mapper may split the scene); aligned copy if the aligner worked."""
        models = [os.path.join(sparse, d) for d in os.listdir(sparse) if os.path.isdir(os.path.join(sparse, d))
                  and not d.startswith("aligned")]
        if not models:
            raise RuntimeError("COLMAP could not align the photos")
        best = max(models, key=lambda m: os.path.getsize(os.path.join(m, "images.bin"))
                   if os.path.exists(os.path.join(m, "images.bin")) else 0)
        job.data["model"] = best
        os.makedirs(os.path.join(sparse, "aligned"), exist_ok=True)
        job.log(f"Using sparse model {os.path.basename(best)}")

    def aligned(job):
        a = os.path.join(sparse, "aligned")
        if os.path.exists(os.path.join(a, "images.bin")):
            job.data["model"] = a
        os.makedirs(os.path.join(work, "sparse_txt"), exist_ok=True)       # model_converter needs it

    def to_xml(job):
        txt = os.path.join(work, "sparse_txt")
        xml = os.path.join(work, f"CAM_{obj}.xml")
        n = colmap_xml.write_xml(txt, xml)
        job.log(f"{n} cameras written to {os.path.basename(xml)}")
        job.data["xml"] = xml

    def collect(job):
        flat = os.path.join(work, "undistorted")              # one folder, photo names = camera labels
        os.makedirs(flat, exist_ok=True)
        for d, _dirs, files in os.walk(os.path.join(dense, "images")):
            for f in files:
                shutil.copy2(os.path.join(d, f), os.path.join(flat, f))
        job.data["result"] = _collect_result(root, work, "OPENSOURCE", job.data["xml"], True, flat)

    c = lambda *a: [colmap] + list(a)
    steps = [
        jobs.Step("Copy photos", prepare, weight=3),
        jobs.Step("Features", c("feature_extractor", "--database_path", db, "--image_path", images,
                                "--ImageReader.camera_model", "OPENCV",
                                "--ImageReader.single_camera_per_folder", "1"), env=env, weight=8),
        jobs.Step("Matching", c("exhaustive_matcher", "--database_path", db), env=env, weight=12),
        jobs.Step("Align cameras", c("mapper", "--database_path", db, "--image_path", images,
                                     "--output_path", sparse), env=env, weight=15),
        jobs.Step("Pick model", pick_model, weight=0.1),
        jobs.Step("Level the model", c("model_orientation_aligner", "--image_path", images,
                                       "--input_path", "{model}", "--output_path",
                                       os.path.join(sparse, "aligned")), env=env, weight=2, ok_codes=(0, 1)),
        jobs.Step("Choose levelled model", aligned, weight=0.1),
        jobs.Step("Undistort", c("image_undistorter", "--image_path", images, "--input_path", "{model}",
                                 "--output_path", dense, "--output_type", "COLMAP"), env=env, weight=5),
        jobs.Step("Cameras to text", c("model_converter", "--input_path", os.path.join(dense, "sparse"),
                                       "--output_path", os.path.join(work, "sparse_txt"), "--output_type", "TXT"),
                  env=env, weight=0.5),
        jobs.Step("Cameras XML", to_xml, weight=0.2),
        jobs.Step("Import into OpenMVS", [tools.openmvs("InterfaceCOLMAP"), "-w", work, "-i", dense,
                                          "-o", "scene.mvs", "--image-folder", os.path.join(dense, "images")],
                  weight=2),
    ] + _openmvs_steps(work, preset, "scene.mvs") + [jobs.Step("Collect result", collect, weight=1)]
    return jobs.Job("Open Source", steps, on_done=on_done,
                    log_path=os.path.join(root, paths.SCAN, paths.OPEN, "logs", "opensource.log"))


def hybrid_job(root, preset="NORMAL", on_done=None):
    found = paths.locate(root)
    if not found["xml"]:
        raise ValueError(f"Export the cameras from Agisoft first: CAM_{found['object']}.xml in 01.CAM_Photos")
    work = tools.work_dir(root, "HYBRID")
    photos = _photos(root)

    def prepare(job):
        for f in glob.glob(os.path.join(work, "scene*")) + glob.glob(os.path.join(work, "depth*.dmap")):
            os.remove(f)
        n = colmap_xml.metashape_xml_with_paths(found["xml"], os.path.join(work, "cameras_paths.xml"), photos)
        if n < 3:
            raise RuntimeError(f"Only {n} aligned camera(s) with a photo")
        job.log(f"{n} cameras with photos")

    def collect(job):
        cam = os.path.join(work, os.path.basename(found["xml"]))
        shutil.copy2(found["xml"], cam)
        job.data["result"] = _collect_result(root, work, "HYBRID", cam, False, None)

    steps = [
        jobs.Step("Prepare cameras", prepare, weight=0.5),
        jobs.Step("Import into OpenMVS", [tools.openmvs("InterfaceMetashape"), "-w", work, "-i", "cameras_paths.xml",
                                          "-o", "scene.mvs", "--output-image-folder", "undistorted"], weight=5),
    ] + _openmvs_steps(work, preset, "scene.mvs") + [jobs.Step("Collect result", collect, weight=1)]
    return jobs.Job("Hybrid", steps, on_done=on_done,
                    log_path=os.path.join(root, paths.SCAN, paths.OPEN, "logs", "hybrid.log"))
