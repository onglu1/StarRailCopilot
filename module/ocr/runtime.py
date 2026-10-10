"""Bound OCR CPU work and use the optional CUDA runtime when available."""
import os
from types import MethodType
import cv2
import numpy as np
import onnxruntime as ort
from pponnxcr.utility import get_model_data

from module.logger import logger


def cuda_recognizer_resize(recognizer, image, max_wh_ratio):
    from pponnxcr.rec.predict_rec import TextRecognizer
    width = recognizer.rec_image_shape[2]
    # Very narrow CUDA convolutions are slower than the model's 320px input
    # width on this runtime. Pad blank space; never stretch the characters.
    normalized = TextRecognizer.resize_norm_img(recognizer, image, max_wh_ratio)
    if normalized.shape[2] < width:
        normalized = np.pad(normalized, ((0, 0), (0, 0), (0, width - normalized.shape[2])))
    return normalized


class TightDetectionResize:
    """Keep PP-OCR's scale/coordinates, padding only to the network stride."""
    def __init__(self, limit_side_len):
        self.limit_side_len = limit_side_len

    def __call__(self, image):
        src_h, src_w = image.shape[:2]
        ratio = min(1.0, self.limit_side_len / max(src_h, src_w))
        if ratio < 1:
            image = cv2.resize(image, (round(src_w * ratio), round(src_h * ratio)))
        height, width = image.shape[:2]
        # Two strides of black context preserve characters near crop edges.
        # Minimal alignment alone clipped a stroke in a real blessing name.
        target_h = min(self.limit_side_len, (height + 31) // 32 * 32 + 64)
        target_w = min(self.limit_side_len, (width + 31) // 32 * 32 + 64)
        return {'image': cv2.copyMakeBorder(image, 0, target_h - height, 0, target_w - width,
                                            cv2.BORDER_CONSTANT, value=(0, 0, 0)),
                'shape': np.array([src_h, src_w, ratio])}


def configure_inference(model, lang):
    # Independent emulator workers must not each spin one pool per CPU core.
    cv2.setNumThreads(2)
    options = ort.SessionOptions()
    options.log_severity_level = 3
    options.intra_op_num_threads = 2
    options.inter_op_num_threads = 1
    options.add_session_config_entry('session.intra_op.allow_spinning', '0')
    options.add_session_config_entry('session.inter_op.allow_spinning', '0')
    providers = ['CPUExecutionProvider']
    if os.environ.get('SRC_OCR_CPU_ONLY') != '1' and 'CUDAExecutionProvider' in ort.get_available_providers():
        if hasattr(ort, 'preload_dlls'):
            ort.preload_dlls()
        providers.insert(0, ('CUDAExecutionProvider', {
            'gpu_mem_limit': 256 * 1024 * 1024,
            'arena_extend_strategy': 'kSameAsRequested',
            'cudnn_conv_algo_search': 'HEURISTIC',
            'cudnn_conv_use_max_workspace': '0',
            'use_tf32': '0',
        }))
    parts = [(model.text_detector, 'det'), (model.text_recognizer, 'rec')]
    if model.use_angle_cls:
        parts.append((model.text_classifier, 'cls'))
    for part, name in parts:
        try:
            session = ort.InferenceSession(get_model_data(lang, name), options, providers=providers)
        except Exception as error:
            if providers == ['CPUExecutionProvider']:
                raise
            logger.warning(f'OCR CUDA initialization failed; using bounded CPU inference: {error}')
            providers = ['CPUExecutionProvider']
            session = ort.InferenceSession(get_model_data(lang, name), options, providers=providers)
        part.predictor = session
        part.input_tensor = session.get_inputs()[0]
        if name == 'rec' and session.get_providers()[0] == 'CUDAExecutionProvider':
            part.resize_norm_img = MethodType(cuda_recognizer_resize, part)
        logger.attr(f'OCR {name} runtime', f'{session.get_providers()[0]}, CPU threads=2, spinning=off')
    detector = model.text_detector
    if all(not isinstance(size, int) for size in detector.input_tensor.shape[2:]):
        operations = detector.preprocess_op.ops
        detector.preprocess_op.ops = (TightDetectionResize(operations[0].limit_side_len), *operations[1:])
