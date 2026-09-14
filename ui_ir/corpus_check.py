"""Offline matched-source compactor comparison; outputs counters, not capture content."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from ui_ir.bridge import _offline_page, invoke

ROOT = Path(__file__).resolve().parents[1]


def producer_hashes():
    files = ['ui_ir/dom/parse.mjs', 'ui_ir/dom/adapter.mjs', 'ui_ir/compact.mjs',
             'ui_ir/codec.mjs', 'ui_ir/validate.mjs', 'ui_ir/registries.mjs',
             'experiments/dom-downsampling/compact.js']
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files}


def corpus():
    entries = []
    for path in sorted((ROOT/'examples/vision-study/captures').glob('*/page.html')):
        entries.append((path.parent.name, path))
    for dataset in ['ewh-dashboard', 'nyt-homepage']:
        manifest = ROOT/'examples'/dataset/'dom-index.json'
        if manifest.exists():
            for document in json.loads(manifest.read_text()).get('documents', []):
                path = Path(document['path'])
                if path.is_file():
                    entries.append((dataset+'-'+document['id'], path))
    return entries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT/'runs/ui-ir-validation/corpus.json')
    parser.add_argument('--profiles', nargs='+', choices=['structure', 'excerpt', 'budget'], default=['structure', 'excerpt', 'budget'])
    parser.add_argument('--limit', type=int)
    args = parser.parse_args(argv)
    inputs = corpus()
    if args.limit:
        inputs = inputs[:args.limit]
    if not inputs:
        raise SystemExit('No local capture corpus present; no comparison was run.')
    results = []
    producers = producer_hashes()
    script = (ROOT/'ui_ir/dom/parse.mjs').read_text().replace('export function parseDOM', 'function parseDOM')
    with _offline_page() as (page, browser_version):
        page.evaluate('(() => {\n'+script+'\nglobalThis.__parseIR=parseDOM;\n})()')
        page.evaluate((ROOT/'experiments/dom-downsampling/compact.js').read_text())
        for dataset, path in inputs:
            raw=path.read_bytes()
            if len(raw)>10_000_000:
                results.append({'dataset':dataset,'status':'skipped_oversize'})
                continue
            source=raw.decode('utf-8')
            start=time.perf_counter()
            parsed=page.evaluate('s => __parseIR(s,{documentId:"d0",networkIsolated:true})',source)
            parse_ms=(time.perf_counter()-start)*1000
            snapshot=hashlib.sha256(raw).hexdigest()
            for profile in args.profiles:
                if producers != producer_hashes():
                    raise RuntimeError('Producer files changed during comparison; discard this partial run and repeat.')
                row={'dataset':dataset,'profile':profile,'source_sha256':snapshot,'source_bytes':len(raw),'parsed_records':len(parsed['records']),'parse_ms':parse_ms}
                try:
                    start=time.perf_counter()
                    legacy=page.evaluate('x=>{const r=compactDOM(x.source,{profile:x.profile,targetRatio:.1});return{report:r.report,bytes:new TextEncoder().encode(r.html).length};}',{'source':source,'profile':profile})
                    row.update(legacy_ms=(time.perf_counter()-start)*1000,legacy_bytes=legacy['bytes'],legacy_passed=legacy['report']['passed'],legacy_elements=legacy['report']['outputElements'])
                    start=time.perf_counter()
                    result=invoke({'operation':'pipeline','input':{'snapshotId':snapshot,'documents':[parsed]},'request':{'profile':profile,'maxBytes':200000,'planRegions':False}})
                    report=result['result']['report']
                    row.update(ir_ms=(time.perf_counter()-start)*1000,ir_nodes=report['viewNodes'],observation_nodes=report['observationNodes'],ir_bytes=report['encodedBytes'],ir_status=report['status'],ir_gaps=len(result['result']['view']['gaps']),status='passed')
                except (ValueError, RuntimeError, TimeoutError) as error:
                    row.update(status='failed',error=str(error)[:1000])
                results.append(row)
                print(f"{dataset} {profile}: {row['status']} · IR {row.get('ir_bytes','—')} bytes · {row.get('ir_status','—')}",flush=True)
                args.out.parent.mkdir(parents=True,exist_ok=True)
                args.out.write_text(json.dumps({'browser_version':browser_version,'documents':len(inputs),'producer_hashes':producers,'results':results,
                    'limits':['Same saved HTML and profile names; IR/text-node schema differs from compact HTML and policies are intentionally more conservative.','IR timing includes subprocess serialization/transport; no tokenizer, model, or user-navigation measurements.','Partitioning disabled for whole-source size comparison; oversize statuses are retained.','No source scripts or network requests executed; local corpus is not a public dataset.']},indent=2)+'\n')
    if any(r['status']=='failed' for r in results):
        raise SystemExit(1)


if __name__=='__main__':
    main()
