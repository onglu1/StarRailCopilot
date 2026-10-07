"""Resolve one explicit strategy source and decide whether a run can reuse it."""
import base64
import binascii
import hashlib
from pathlib import Path
import re


PRESETS = ('template', 'template2', 'template3')
NATIVE_SOURCES = ('random', 'code', 'code_pool', 'sequence')


def extract_code(text):
    text = (text or '').strip()
    match = re.search(r'##([A-Za-z0-9+/=]{20,120})##', text)
    payload = match.group(1) if match else text
    if not re.fullmatch(r'[A-Za-z0-9+/]{20,120}={0,2}', payload):
        return None
    try:
        decoded = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error):
        return None
    if len(decoded) < 32:
        return None
    return f'##{payload}##'


def extract_code_list(text):
    text = (text or '').strip()
    if '##' in text:
        entries = re.findall(r'##[^#\r\n]*##', text)
        if text.count('##') != len(entries) * 2:
            raise ValueError('攻略列表含有不完整的##分隔符，请粘贴完整分享内容')
    else:
        entries = [line.strip() for line in text.splitlines() if line.strip()]
    codes = [extract_code(entry) for entry in entries]
    if not codes or not all(codes):
        raise ValueError('攻略列表为空或含有不完整的码，请粘贴完整分享内容或每行一个纯码')
    return codes


def strategy_request(config):
    source = config.CurrencyWars_Strategy
    request = {'source': source}
    if source == 'code':
        code = extract_code(config.CurrencyWars_ShareCode)
        if not code:
            raise ValueError('攻略码不完整或格式错误，请粘贴游戏复制的完整分享文本；不会回退到旧攻略')
        request['code'] = code
    elif source == 'code_pool':
        request['codes'] = list(dict.fromkeys(extract_code_list(config.CurrencyWars_RandomCodes)))
    elif source == 'sequence':
        request['codes'] = extract_code_list(config.CurrencyWars_SequenceCodes)
    elif source == 'file':
        value = (config.CurrencyWars_StrategyFile or '').strip()
        if not value:
            raise ValueError('选择自定义文件后必须填写攻略 JSON 路径')
        path = Path(value).resolve()
        request.update(path=str(path), digest=hashlib.sha256(path.read_bytes()).hexdigest())
    elif source not in ('random', 'preset_pool', *PRESETS):
        raise ValueError(f'未知攻略来源：{source}')
    return request


def can_resume_strategy(active, request):
    current = active.get('strategy')
    if not current or isinstance(current, str) and current not in PRESETS:
        return False
    if active.get('pending_settlement'):
        return True
    saved = active.get('strategy_request')
    if saved is not None:
        return saved == request
    # Migrate old run records by the actual selected strategy, not by a
    # missing fingerprint that would randomly replace every resumed game.
    source = request['source']
    if isinstance(current, dict) and current.get('path'):
        code = extract_code(current.get('code'))
        return (source == 'random'
                or source == 'code' and code == request['code']
                or source == 'code_pool' and code in request['codes'])
    return source == current or source == 'preset_pool' and current in PRESETS
