"""Replaceable rejected baseline. No labels or reference-video lookup at inference."""
import base64
import io
import json
import math
import time

from scripts.full_scan import WindowScorer, THRESHOLD, decode_targets, window_grid

PROMPT = (
    'Inspect eight chronological frames from a cash-operation video. '
    'Use visual evidence only. Do not identify people or faces. '
    'Do not infer intent, account records, authorization, or unseen actions. '
    'Do not invent laws. This is screening for possible issues for human review. '
    'Unusual appearance alone is not a violation. Report only clearly visible signs '
    'of a possible cash-handling or physical-security breach. '
    'Return ONLY one JSON object with exactly one key: '
    '{"verdict":"violation"} or {"verdict":"no_violation"}. '
    'Do not include explanations.')

SOURCE_NOTE = (
    ' Экспериментальный кандидат: качество детектора отклонено на development. '
    'Справочный документ: постановление Правления НБРК от 29.11.2019 №231, '
    'Правила осуществления кассовых операций и операций по инкассации банкнот, монет и ценностей; '
    'https://adilet.zan.kz/rus/docs/V1900019680. '
    'Применимость к событию и конкретный пункт не подтверждены; это не юридическое обоснование.')


class RejectedBaseline:
    def __init__(self):
        self.scorer = WindowScorer(PROMPT)

    def analyze(self, path, deadline):
        import av
        def budget():
            if time.monotonic() >= deadline:
                raise TimeoutError('deadline')
        budget()
        with av.open(str(path)) as c:
            if not c.streams.video:
                raise ValueError('no_video')
            s = c.streams.video[0]
            duration = float(s.duration * s.time_base) if s.duration else (c.duration or 0) / 1e6
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('invalid_duration')
        # Full coverage or explicit failure; never silently truncate a long recording.
        windows = window_grid(duration)
        if len(windows) > 80:
            raise ValueError('video_exceeds_baseline_capacity')
        frames = decode_targets(path, windows)
        best = None
        for targets in windows:
            budget()
            score = self.scorer.score([frames[t][0] for t in targets])['score']
            if best is None or score > best[0]:
                best = score, targets
        budget()
        if best[0] < THRESHOLD:
            return {'verdict': 'no_violation', 'violations': []}
        targets = best[1]
        # Description does NOT turn this rejected score into a validated detector.
        description = self.describe([frames[t][0] for t in targets])
        pts = frames[targets[4]][1]
        del frames
        budget()
        evidence = self.evidence(path, pts)
        return {'verdict': 'violation', 'violations': [{
            'type': description['type'], 'timecode_sec': pts,
            'description': description['description'] + SOURCE_NOTE,
            'evidence_frames': [evidence]}]}

    def describe(self, images):
        s = self.scorer
        prompt = (
            'Describe the visible action in these chronological frames for human review. '
            'The window is an unverified candidate, NOT proof of a violation. '
            'Do not identify people or faces. Do not infer intent, authorization, accounts or unseen actions. '
            'Do not mention laws, regulations, document numbers or links. '
            'If no clear irregularity is visible, say so explicitly. '
            'Return ONLY JSON with type (short Russian action label) and description '
            '(one short Russian sentence about visible evidence and its uncertainty).')
        content = [{'type': 'text', 'text': prompt}] + [{'type': 'image'} for _ in images]
        text = s.processor.apply_chat_template([{'role': 'user', 'content': content}],
                                              tokenize=False, add_generation_prompt=True)
        inputs = s.processor(text=[text], images=images, return_tensors='pt').to('cuda')
        with s.torch.inference_mode():
            output = s.model.generate(**inputs, max_new_tokens=220, do_sample=False, use_cache=True)
        raw = s.processor.decode(output[0, inputs.input_ids.shape[-1]:], skip_special_tokens=True)
        obj = json.loads(raw)
        if not isinstance(obj, dict) or set(obj) != {'type', 'description'}:
            raise ValueError('invalid_description_schema')
        for key, limit in [('type', 160), ('description', 1600)]:
            if not isinstance(obj[key], str) or not 1 <= len(obj[key].strip()) <= limit:
                raise ValueError('invalid_description_text')
        return obj

    @staticmethod
    def evidence(path, pts):
        import av
        with av.open(str(path)) as c:
            s = c.streams.video[0]
            origin = float((s.start_time or 0) * s.time_base)
            for f in c.decode(s):
                if f.pts is None:
                    continue
                stamp = float(f.pts * f.time_base) - origin
                if abs(stamp - pts) < 1e-7:
                    buf = io.BytesIO()
                    # Original frame, no crop, resize or annotation. JPEG is required by contract.
                    f.to_image().save(buf, format='JPEG', quality=90)
                    return {'timestamp_sec': stamp, 'image_base64': base64.b64encode(buf.getvalue()).decode('ascii')}
        raise ValueError('evidence_pts_not_found')
