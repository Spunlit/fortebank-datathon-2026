"""Reusable offline temporal scan. No labels, filenames or duration enter model inputs."""
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OFFSETS = (-2, -1.5, -1, -0.5, 0, 0.5, 1, 2)
STRIDE = 3.0
THRESHOLD = -27.75


def window_grid(duration):
    """Four-second windows, one-second overlap, deterministic terminal window."""
    last = duration - 0.05
    if last < 4:
        raise ValueError('Video too short for this experimental configuration')
    starts = [float(x * STRIDE) for x in range(math.floor((last - 4) / STRIDE) + 1)]
    if last - 4 - starts[-1] > 1e-7:
        starts.append(last - 4)
    return [[round(start + 2 + off, 8) for off in OFFSETS] for start in starts]


def decode_targets(path, windows):
    """Decode only video once. Keep nearest PTS images needed by the fixed grid."""
    import av
    targets = sorted(set(t for window in windows for t in window))
    selected = {}
    previous = None
    index = 0
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        origin = float((stream.start_time or 0) * stream.time_base)
        for frame in container.decode(stream):
            if frame.pts is None:
                raise ValueError('Missing PTS')
            stamp = float(frame.pts * frame.time_base) - origin
            if previous is not None and stamp <= previous[1]:
                raise ValueError('Non-monotonic PTS')
            while index < len(targets) and stamp >= targets[index]:
                target = targets[index]
                chosen, pts = frame, stamp
                if previous is not None and abs(previous[1] - target) < abs(stamp - target):
                    chosen, pts = previous
                image = chosen.to_image()
                image.thumbnail((448, 768))
                selected[target] = (image, pts)
                index += 1
            if index == len(targets):
                break
            previous = frame, stamp
    if index != len(targets):
        raise ValueError('Incomplete temporal coverage')
    for window in windows:
        if len(set(selected[t][1] for t in window)) != 8:
            raise ValueError('Repeated PTS within window')
    return selected


def configure_offline():
    for key in ('HF_HOME', 'TORCH_HOME', 'XDG_CACHE_HOME', 'TRITON_CACHE_DIR'):
        os.environ[key] = str(ROOT / '.cache' / key.lower())
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      HF_HUB_DISABLE_TELEMETRY='1', HF_HUB_DISABLE_IMPLICIT_TOKEN='1',
                      TOKENIZERS_PARALLELISM='false', TEMP=str(ROOT / '.tmp'), TMP=str(ROOT / '.tmp'))


class WindowScorer:
    def __init__(self, prompt):
        import torch
        from transformers import AutoProcessor, BitsAndBytesConfig, Qwen3VLForConditionalGeneration
        self.torch = torch
        torch.manual_seed(42)
        torch.cuda.init()
        torch.cuda.reset_peak_memory_stats()
        model_dir = ROOT / '.cache/models/Qwen3-VL-4B-Instruct'
        self.processor = AutoProcessor.from_pretrained(
            model_dir, local_files_only=True, trust_remote_code=False, use_fast=False)
        self.model = Qwen3VLForConditionalGeneration.from_pretrained(
            model_dir, local_files_only=True, trust_remote_code=False, device_map={'': 0},
            torch_dtype=torch.bfloat16, attn_implementation='sdpa',
            quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
                bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16))
        self.model.eval()
        self.prompt = prompt
        tokenizer = self.processor.tokenizer
        self.label_tokens = {s: tokenizer.encode(s, add_special_tokens=False)
                             for s in ('violation', 'no_violation')}

    def score(self, images):
        import time
        torch = self.torch
        started = time.perf_counter()
        content = [{'type': 'text', 'text': self.prompt}] + [{'type': 'image'} for _ in images]
        prefix = self.processor.apply_chat_template([{'role': 'user', 'content': content}],
            tokenize=False, add_generation_prompt=True) + '{"verdict":"'
        tokenizer = self.processor.tokenizer
        tokens = self.label_tokens['violation']
        assert tokenizer.encode(prefix + 'violation', add_special_tokens=False) == (
            tokenizer.encode(prefix, add_special_tokens=False) + tokens)
        inputs = self.processor(text=[prefix], images=images, return_tensors='pt').to('cuda')
        token_count = int(inputs.input_ids.shape[-1])
        ids = torch.tensor([tokens], device='cuda')
        inputs['input_ids'] = torch.cat((inputs.input_ids, ids), dim=-1)
        inputs['attention_mask'] = torch.cat((inputs.attention_mask, torch.ones_like(ids)), dim=-1)
        # Identical first branch to round 6, including BF16 and the appended choice.
        with torch.inference_mode():
            output = self.model(**inputs, use_cache=False, logits_to_keep=len(tokens) + 1)
            logp = output.logits[0, 0].float().log_softmax(-1)
            margin = float(logp[self.label_tokens['violation'][0]] - logp[self.label_tokens['no_violation'][0]])
        torch.cuda.synchronize()
        if not math.isfinite(margin):
            raise ValueError('Nonfinite score')
        return {'score': margin, 'inference_sec': time.perf_counter() - started,
                'input_tokens': token_count}
