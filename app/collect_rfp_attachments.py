from __future__ import annotations
import argparse, json, tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from app.chunking import build_chunks
from app.g2b_collector import BASE, _key
from app.parsers import parse_document
from app.schemas import AccessStatus, DocumentKind, DocumentManifest
from app.source_loader import reject_pii_blocks, verify_rfp_attachment

def _section(text: str) -> str:
    for label, terms in {"제출서류": ("제출서류", "제출"), "참가자격": ("참가자격", "입찰참가"), "평가기준": ("평가", "배점")}.items():
        if any(term in text for term in terms): return label
    return "RFP 본문"

def main() -> None:
    parser=argparse.ArgumentParser(); parser.add_argument('--limit',type=int,default=5); args=parser.parse_args(); root=Path(__file__).parents[1]
    q={'serviceKey':_key(root),'pageNo':'1','numOfRows':'100','inqryDiv':'1','inqryBgnDt':'202501010000','inqryEndDt':'202501312359','type':'json'}
    data=json.loads(urlopen(BASE+'?'+urlencode(q),timeout=30).read().decode('utf8')); items=data['response']['body']['items']; manifests=[]; chunks=[]; failures=[]
    for item in items:
        for number in range(1,11):
            if len(manifests)>=args.limit: break
            url=item.get(f'ntceSpecDocUrl{number}','')
            if not url: continue
            try:
                digest,payload=verify_rfp_attachment(url,'공개 나라장터 공고의 포트폴리오 제한 수집(사용자 승인)')
                suffix='.pdf' if payload.startswith(b'%PDF') else '.hwpx'
                with tempfile.TemporaryDirectory() as directory:
                    path=Path(directory)/f'attachment{suffix}'; path.write_bytes(payload); blocks=parse_document(path); reject_pii_blocks(blocks); blocks=[block.__class__(block.page,block.text,block.content_type,block.parser,block.confidence,_section(block.text)) for block in blocks]
                no=item['bidNtceNo']; manifest=DocumentManifest(document_id=f'g2b-rfp-{no.lower()}-{number}',title=f"{item['bidNtceNm']} 첨부 {number}",source_url=url,issuing_organization=item.get('dminsttNm') or item['ntceInsttNm'],collected_at=datetime.now(UTC),document_kind=DocumentKind.PDF if suffix=='.pdf' else DocumentKind.HWPX,access_status=AccessStatus.CONFIRMED_PUBLIC,usage_terms_checked=True,usage_basis='공개 나라장터 공고의 포트폴리오 제한 수집(사용자 승인)',notice_number=no)
                manifests.append(manifest); chunks.extend(build_chunks(manifest,blocks)); failures.append({'document_id':manifest.document_id,'sha256':digest,'status':'indexed'})
            except Exception as exc: failures.append({'notice_number':item.get('bidNtceNo'),'attachment':number,'status':'excluded','reason':type(exc).__name__})
        if len(manifests)>=args.limit: break
    (root/'data'/'g2b-rfp-manifest.json').write_text(json.dumps([m.model_dump(mode='json') for m in manifests],ensure_ascii=False,indent=2),encoding='utf8'); (root/'data'/'g2b-rfp-chunks.json').write_text(json.dumps([c.model_dump(mode='json') for c in chunks],ensure_ascii=False,indent=2),encoding='utf8'); (root/'data'/'g2b-rfp-report.json').write_text(json.dumps(failures,ensure_ascii=False,indent=2),encoding='utf8'); print(json.dumps({'documents':len(manifests),'chunks':len(chunks),'events':len(failures)},ensure_ascii=False))
if __name__=='__main__': main()
