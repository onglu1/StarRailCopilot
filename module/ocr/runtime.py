"""Bound OCR CPU work and use the optional CUDA runtime when available."""
import os
import cv2
import onnxruntime as ort
from pponnxcr.utility import get_model_data

from module.logger import logger


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
        logger.attr(f'OCR {name} runtime', f'{session.get_providers()[0]}, CPU threads=2, spinning=off')
