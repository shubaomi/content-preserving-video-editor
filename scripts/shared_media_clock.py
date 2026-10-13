"""QA-C: narrowly adapt an intent-bound duplicate-media warning, never its raw result.

The approval reference is a drift binding, not identity authentication. The caller
must possess the user's approval. Runtime fixtures are not real-render evidence;
unchanged-time preview/render parity remains a separate mandatory gate.
"""
from __future__ import annotations

import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
from typing import Any

CODE = 'duplicate_media_discovery_risk'


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    _require(isinstance(value, dict), 'JSON object required')
    return value


def file_ref(path: Path) -> dict[str, str]:
    path = path.resolve(strict=True)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return {'path': str(path), 'sha256': digest.hexdigest()}


def _bound(ref: dict[str, str]) -> Path:
    _require(isinstance(ref, dict) and isinstance(ref.get('path'), str), 'file reference required')
    path = Path(ref['path'])
    _require(path.is_absolute(), 'absolute reference required')
    _require(file_ref(path)['sha256'] == ref.get('sha256'), f'stale file: {path}')
    return path.resolve(strict=True)


def _number(value: Any) -> float:
    _require(not isinstance(value, bool), 'boolean is not a number')
    number = float(value)
    _require(math.isfinite(number), 'finite number required')
    return number


class _HTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.nodes: list[dict[str, Any]] = []
        self.stack: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        _require(len(dict(attrs)) == len(attrs), 'duplicate HTML attribute')
        node = {'tag': tag, 'attrs': dict(attrs), 'parents': list(self.stack)}
        self.nodes.append(node)
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.stack.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack)-1, -1, -1):
            if self.stack[index]['tag'] == tag:
                del self.stack[index:]
                break


def _local(root: Path, src: str) -> Path:
    _require(isinstance(src, str) and bool(src) and not any(c in src for c in ['?', '#', ':']),
             'only unchanged relative local media/scripts are supported')
    path = (root/src).resolve(strict=True)
    _require(path.is_relative_to(root.resolve()), 'asset escapes project')
    return path


def inspect_project(project_root: Path, intent: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Re-derive exact static media identities and event associations from HTML."""
    root = project_root.resolve(strict=True)
    parser = _HTML()
    parser.feed((root/'index.html').read_text(encoding='utf-8'))
    nodes = parser.nodes
    _require(not any(n['tag'] == 'link' and 'stylesheet' in n['attrs'].get('rel', '').lower().split()
                     for n in nodes), 'external stylesheets unsupported by shared-clock adapter')
    _require(not any(n['tag'] == 'script' and n['attrs'].get('type', '').lower() == 'module'
                     for n in nodes), 'module scripts unsupported by shared-clock adapter')
    ids = [n['attrs']['id'] for n in nodes if 'id' in n['attrs']]
    _require(len(ids) == len(set(ids)), 'duplicate DOM id')
    compositions = [n for n in nodes if 'data-composition-id' in n['attrs']]
    _require(len(compositions) == 1, 'one standalone composition required')
    attrs = compositions[0]['attrs']
    _require(attrs['data-composition-id'] == intent['composition_id'], 'composition mismatch')
    duration, fps = _number(intent['duration']), _number(intent['fps'])
    _require(duration > 0 and fps > 0 and duration*fps <= 100000, 'invalid sample extent')
    _require(_number(attrs['data-duration']) == duration and _number(attrs['data-fps']) == fps,
             'sample duration/fps mismatch')
    _require(_number(attrs.get('data-start', 0)) == 0, 'sample root is not zero based')
    files = [_bound(ref) for ref in intent['project_files']]
    _require(len(files) == len(set(files)), 'duplicate project file reference')
    discovered = {root/'index.html'} | {_local(root, n['attrs']['src']) for n in nodes if 'src' in n['attrs']}
    _require(set(files) == discovered, 'project file inventory does not exactly cover HTML and sources')
    for path in files:
        if path.suffix.lower() in {'.js', '.html'}:
            _require(not re.search(r'\b(?:import|importScripts|require)\s*(?:\(|[\"\x27{*])',
                                   path.read_text(encoding='utf-8')),
                     'imported resources unsupported by shared-clock adapter')
    video_source, audio_source = _bound(intent['video_source']), _bound(intent['audio_source'])
    events = payload.get('events', [])
    _require(payload.get('direction') == 'authentic_product_editorial', 'wrong editorial direction')
    _require(events and all(e.get('sound', {}).get('decision') == 'intentionally_silent' for e in events),
             'shared-clock route requires original-audio-only plan')
    shots = [e for e in events if e.get('recipe_id') == 'A01']
    instances = intent['instances']
    _require(bool(shots) and [i['event_id'] for i in instances] == [e['instance_id'] for e in shots],
             'intent must cover exactly the ordered A01 events')
    expected_ids = [intent['base_video_id']] + [i['video_id'] for i in instances]
    _require(len(expected_ids) == len(set(expected_ids)), 'intent video ids are not unique')
    _require(len({i['host_id'] for i in instances}) == len(instances), 'intent hosts are not unique')
    for prior, event in zip(shots, shots[1:]):
        _require(_number(prior['output_end']) <= _number(event['output_start']), 'competing A01 windows')
    for event in shots:
        _require(0 <= _number(event['output_start']) < _number(event['output_end']) <= duration,
                 'A01 outside sample')
    media = []
    videos = [n for n in nodes if n['tag'] == 'video']
    audios = [n for n in nodes if n['tag'] == 'audio']
    _require([n['attrs'].get('id') for n in videos] == expected_ids, 'extra/missing/reordered source video')
    _require(len(audios) == 1 and audios[0]['attrs'].get('id') == intent['audio_id'], 'duplicate/missing original audio')
    for node in videos + audios:
        attrs = node['attrs']
        is_video = node['tag'] == 'video'
        source = _local(root, attrs.get('src', ''))
        _require(source == (video_source if is_video else audio_source), 'wrong media source')
        _require(_number(attrs.get('data-start', 0)) == 0 and _number(attrs.get('data-media-start', 0)) == 0,
                 'media clocks must start at zero')
        _require(_number(attrs['data-duration']) == duration, 'media does not cover full sample')
        _require('loop' not in attrs and all(_number(attrs.get(k, 1)) == 1 for k in
                 ['data-playback-rate', 'data-speed', 'data-volume']), 'loop/rate/gain changed')
        _require(('muted' in attrs) == is_video, 'duplicate audio or muted voice')
        hosts = [p for p in node['parents'] if 'data-semantic-event-id' in p['attrs']]
        host_id = hosts[-1]['attrs'].get('id') if hosts else None
        if is_video and attrs['id'] != intent['base_video_id']:
            instance = next(i for i in instances if i['video_id'] == attrs['id'])
            _require(len(hosts) == 1 and host_id == instance['host_id'] and
                     hosts[0]['attrs']['data-semantic-event-id'] == instance['event_id'], 'wrong parent gate/plan association')
            _require('clip' not in hosts[0]['attrs'].get('class', '').split(), 'host gate cannot own framework clip')
        else:
            _require(not hosts, 'base/voice unexpectedly nested in event')
        media.append({'id':attrs['id'],'tag':node['tag'],'src':str(source),'start':0.0,
                      'mediaStart':0.0,'duration':duration,'muted':is_video,'host_id':host_id,
                      'playbackRate':1,'defaultPlaybackRate':1,'volume':1,'loop':False,
                      'currentSrcMatchesDeclared':True})
    return {'media': media, 'video_ids': expected_ids}


def current_bindings(project_root: Path, intent_path: Path) -> dict[str, str]:
    intent = _read(intent_path)
    _require(intent.get('schema_version') == 1 and intent.get('kind') == 'shared_source_clock_intent' and
             intent.get('authorization') == 'approved_qa_c_minimal_adaptation', 'explicit QA-C intent required')
    refs = [intent['approval'], intent['payload'], intent['video_source'], intent['audio_source'], *intent['project_files']]
    bindings = {str(_bound(ref)): ref['sha256'] for ref in refs}
    bindings[str(intent_path.resolve())] = file_ref(intent_path)['sha256']
    inspect_project(project_root, intent, _read(_bound(intent['payload'])))
    return bindings


def sample_times(intent: dict[str, Any], payload: dict[str, Any]) -> list[float]:
    duration, fps = _number(intent['duration']), _number(intent['fps'])
    times = [i/fps for i in range(math.ceil(duration*fps))]
    for event in payload['events']:
        if event['recipe_id'] == 'A01':
            for edge in [event['output_start'], event['output_end']]:
                times.extend(t for t in [edge-0.0001, edge+0.0001] if 0 <= t < duration)
    return sorted(set(times))


def build_shared_clock_adaptation(*, project_root: Path, intent_path: Path,
                                 raw_strict_path: Path, runtime_path: Path) -> dict[str, Any]:
    bindings = current_bindings(project_root, intent_path)
    intent, raw, runtime = _read(intent_path), _read(raw_strict_path), _read(runtime_path)
    payload = _read(_bound(intent['payload']))
    actual = inspect_project(project_root, intent, payload)
    _require(raw.get('exit_code') == 1 and raw.get('inputs') == bindings, 'raw strict exit/input binding invalid')
    command = raw.get('command', [])
    tool = _bound(raw['tool'])
    _require(isinstance(command, list) and len(command) >= 6 and command[2] == 'check' and
             Path(command[1]).resolve() == tool and Path(command[3]).resolve() == project_root.resolve() and
             command[4:6] == ['--strict', '--json'], 'exact bound strict tool/project command required')
    _require(len(command) == 6 or (len(command) == 8 and command[6] == '--at' and
             all(0 <= _number(t) < intent['duration'] for t in command[7].split(','))),
             'unexpected strict check arguments')
    strict = _read(_bound(raw['stdout']))
    _require(strict.get('ok') is False and strict.get('strict') is True and strict.get('browserSkipped') is False,
             'must preserve executed failed strict payload')
    findings = strict.get('lint', {}).get('findings', [])
    _require(len(findings) == 1, 'exactly one duplicate-media finding required')
    finding = findings[0]
    count = len(actual['video_ids'])
    _require(finding.get('code') == CODE and finding.get('severity') == 'warning' and
             finding.get('message') == f'Detected {count} matching video entries with the same source/start/duration.' and
             Path(finding.get('sourceFile', '')).resolve() == (project_root/'index.html').resolve(),
             'warning is not the exact intent-bound duplicate group')
    for name in ['lint','runtime','layout','motion','contrast']:
        section = strict.get(name, {})
        _require(section.get('ok') is True and section.get('errorCount') == 0 and
                 section.get('warningCount') == (1 if name == 'lint' else 0), 'other strict error/warning remains')
        _require(section.get('findings') == (findings if name == 'lint' else []), 'unexpected strict finding')
    _require(runtime.get('schema_version') == 1 and runtime.get('producer') == 'shared-media-clock-runtime-v1',
             'wrong runtime evidence producer')
    _require(_bound(runtime['collector']) == Path(__file__).resolve(), 'wrong runtime collector')
    _bound(runtime['browser'])
    _require(runtime.get('inputs') == bindings and runtime.get('media') == actual['media'], 'runtime/source drift')
    times = sample_times(intent, payload)
    expected_rows = [(d,t) for d,values in [('forward',times),('reverse',list(reversed(times)))] for t in values]
    rows = runtime.get('rows', [])
    _require(len(rows) == len(expected_rows), 'incomplete runtime frame/boundary evidence')
    shots = {e['instance_id']:e for e in payload['events'] if e['recipe_id'] == 'A01'}
    for row, (direction, timestamp) in zip(rows, expected_rows, strict=True):
        _require(row.get('direction') == direction and _number(row.get('time')) == timestamp, 'wrong runtime sampling order/time')
        visible = [intent['base_video_id']] + [i['video_id'] for i in intent['instances']
            if shots[i['event_id']]['output_start'] <= timestamp < shots[i['event_id']]['output_end']]
        _require(row.get('active_video_ids') == visible and len(visible) <= 2, 'source gate missing/competing/stale')
        _require(row.get('media') == actual['media'], 'runtime media identity/clock/audio changed during seek')
    return {'schema_version':1,'kind':'shared_source_clock_strict_adaptation','effective_status':'pass',
            'raw_exit_code':1,'raw_strict_status':'failed','adapted_code':CODE,
            'adaptation_scope':'only exact intentional shared-source group; no general warning exemption',
            'inputs':bindings,'intent':file_ref(intent_path),'raw_strict':file_ref(raw_strict_path),
            'raw_stdout':file_ref(_bound(raw['stdout'])),'tool':raw['tool'],'runtime':file_ref(runtime_path),
            'implementation':file_ref(Path(__file__)),'accepted_finding':finding,
            'duplicate_video_ids':actual['video_ids'],'verified_runtime_samples':len(rows),
            'limitations':['This adapts one strict warning, not rendering or unchanged-time parity.',
                           'Approval reference is drift-bound; caller owns actual user authorization.']}


def validate_shared_clock_adaptation(receipt_path: Path, *, project_root: Path, intent_path: Path,
                                     raw_strict_path: Path, runtime_path: Path) -> list[str]:
    try:
        expected = build_shared_clock_adaptation(project_root=project_root, intent_path=intent_path,
            raw_strict_path=raw_strict_path, runtime_path=runtime_path)
        return [] if _read(receipt_path) == expected else ['shared-clock adaptation receipt drift']
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        return [f'shared-clock adaptation invalid: {exc}']


RUNTIME_SCRIPT = r'''({times, compositionId}) => {
  const master=window.__timelines?.[compositionId];
  if(!master || typeof master.seek!=='function') throw Error('seekable master missing');
  const visible=(element)=>{
    let opacity=1;
    for(let e=element;e;e=e.parentElement){
      const s=getComputedStyle(e);
      if(s.display==='none'||s.visibility==='hidden') return false;
      opacity*=Number(s.opacity);
    }
    if(opacity!==0 && Math.abs(opacity-1)>1e-8) throw Error('non-discrete media gate');
    return opacity>0;
  };
  const rows=[];
  const media=()=>[...document.querySelectorAll('video'),...document.querySelectorAll('audio')].map(v=>{
    if(v.playbackRate!==1||v.defaultPlaybackRate!==1||v.volume!==1||v.loop) throw Error('media rate/gain/loop changed');
    if(!v.currentSrc || v.currentSrc!==v.src) throw Error('media currentSrc differs from declared source');
    return {id:v.id,tag:v.tagName.toLowerCase(),src:v.getAttribute('src'),
      start:Number(v.dataset.start||0),mediaStart:Number(v.dataset.mediaStart||0),
      duration:Number(v.dataset.duration),muted:v.muted,
      host_id:v.closest('[data-semantic-event-id]')?.id||null,
      playbackRate:v.playbackRate,defaultPlaybackRate:v.defaultPlaybackRate,volume:v.volume,loop:v.loop,
      currentSrcMatchesDeclared:v.currentSrc===v.src};
  });
  for(const direction of ['forward','reverse']){
    for(const time of direction==='forward'?times:[...times].reverse()){
      master.pause().seek(time,false);
      rows.push({direction,time,active_video_ids:[...document.querySelectorAll('video')].filter(visible).map(v=>v.id),media:media()});
    }
  }
  return {rows,media:media()};
}'''


def collect_shared_clock_runtime(*, project_root: Path, intent_path: Path, browser_path: Path,
                                 browser_project_root: Path | None = None) -> dict[str, Any]:
    """Actual read-only Playwright DOM capture; optional alias must be same directory."""
    from playwright.sync_api import sync_playwright
    bindings = current_bindings(project_root, intent_path)
    intent = _read(intent_path)
    payload = _read(_bound(intent['payload']))
    entry = browser_project_root or project_root
    _require(entry.samefile(project_root), 'browser alias must address the same project')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=str(browser_path), headless=True)
        try:
            page = browser.new_page()
            page.goto((entry/'index.html').as_uri(), wait_until='load')
            page.wait_for_function("[...document.querySelectorAll('video,audio')].every(v=>v.readyState>=1 && v.currentSrc)")
            result = page.evaluate(RUNTIME_SCRIPT, {'times':sample_times(intent,payload),'compositionId':intent['composition_id']})
            browser_version = browser.version
        finally:
            browser.close()
    for inventory in [result['media'], *(row['media'] for row in result['rows'])]:
        for media in inventory:
            media['src'] = str(_local(project_root.resolve(), media['src']))
    _require(current_bindings(project_root, intent_path) == bindings, 'inputs changed during runtime capture')
    return {'schema_version':1,'producer':'shared-media-clock-runtime-v1','collector':file_ref(Path(__file__)),
            'browser':file_ref(browser_path),'browser_version':browser_version,'inputs':bindings,**result}
