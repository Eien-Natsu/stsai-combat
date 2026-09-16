from __future__ import annotations
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from .util import atomic_json

def doctor(output="runs/doctor.json",require_cuda=False):
    report={"python":sys.version,"platform":platform.platform(),"cpu_logical":os.cpu_count(),
            "free_disk_bytes":shutil.disk_usage(Path.cwd()).free,"cuda_verified":False,
            "native_verified":False,"errors":[]}
    try:
        text=subprocess.check_output(["nvidia-smi","--query-gpu=name,memory.total,driver_version","--format=csv,noheader"],text=True,timeout=10)
        report["nvidia_smi"]=text.strip()
    except (OSError,subprocess.SubprocessError) as exc:report["nvidia_smi_error"]=str(exc)
    try:
        import torch
        report["torch"]=str(torch.__version__);report["torch_cuda_runtime"]=torch.version.cuda
        report["cuda_available"]=torch.cuda.is_available()
        if torch.cuda.is_available():
            torch.set_num_threads(2)
            prop=torch.cuda.get_device_properties(0)
            report.update(gpu_name=prop.name,gpu_memory_bytes=prop.total_memory,
                          compute_capability=list(torch.cuda.get_device_capability(0)),
                          compiled_architectures=torch.cuda.get_arch_list())
            from .scenarios import make_scenario,make_env
            from .encoding import encode,collate_encoded
            from .model import CombatNet,ModelConfig
            scenario,seed,_=make_scenario("reference_v1","val",0)
            obs=make_env("reference_v1",scenario,seed).observe()
            batch={k:v.cuda() for k,v in collate_encoded([encode(obs)]*2).items()}
            net=CombatNet(ModelConfig(d_model=96,layers=2,heads=4)).cuda()
            amp=torch.cuda.is_bf16_supported()
            with torch.autocast("cuda",dtype=torch.bfloat16,enabled=amp):
                prediction=net(batch);loss=prediction["value"].mean()+prediction["outcome_logits"].square().mean()
            loss.backward();torch.cuda.synchronize()
            if not all(p.grad is None or torch.isfinite(p.grad).all() for p in net.parameters()):
                raise RuntimeError("GPU backward produced nonfinite gradients")
            report["cuda_verified"]=True;report["bf16_tested"]=amp
            report["recommended_profile"]="configs/rtx5070_8gb.json" if prop.total_memory<10*1024**3 else "configs/rtx5070_12gb.json"
    except (ImportError,RuntimeError) as exc:report["errors"].append(f"torch/CUDA: {exc}")
    try:
        from .native import engine_metadata
        report["native"]=engine_metadata();report["native_verified"]=True
    except (ImportError,RuntimeError) as exc:report["native_error"]=str(exc)
    report["native_verified_meaning"]="Extension imports only, NOT original-game correctness"
    atomic_json(output,report)
    if require_cuda and not report["cuda_verified"]:
        raise RuntimeError(f"GPU smoke test failed; inspect {output}. Do not proceed with a CPU fallback.")
    return report
