from __future__ import annotations
import argparse, json, os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from app.chunking import build_chunks
from app.parsers import ParsedBlock
from app.schemas import AccessStatus, DocumentKind, DocumentManifest

BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc"
def _key(root: Path) -> str:
    for line in (root / '.env').read_text(encoding='utf8').splitlines():
        if line.startswith('G2B_SERVICE_KEY='): return line.split('=',1)[1].strip()
    return os.getenv('G2B_SERVICE_KEY','')
def main() -> None:
    p=argparse.ArgumentParser(); p.add_argument('--from-date',default='202501010000'); p.add_argument('--to-date',default='202501312359'); p.add_argument('--limit',type=int,default=30); a=p.parse_args(); root=Path(__file__).parents[1]
    q={'serviceKey':_key(root),'pageNo':'1','numOfRows':str(a.limit),'inqryDiv':'1','inqryBgnDt':a.from_date,'inqryEndDt':a.to_date,'type':'json'}
    if not q['serviceKey']: raise ValueError('G2B_SERVICE_KEY가 필요합니다.')
    data=json.loads(urlopen(BASE+'?'+urlencode(q),timeout=30).read().decode('utf8')); response=data.get('response',{});
    if response.get('header',{}).get('resultCode')!='00': raise ValueError('나라장터 API 응답 오류')
    items=response['body'].get('items',[]); items=items.get('item',[]) if isinstance(items,dict) else items; manifests=[]; chunks=[]
    for item in items:
        no=item['bidNtceNo']; url=item.get('bidNtceDtlUrl') or item.get('bidNtceUrl');
        if not url: continue
        m=DocumentManifest(document_id=f"g2b-service-{no.lower()}",title=item['bidNtceNm'],source_url=url,issuing_organization=item.get('dminsttNm') or item['ntceInsttNm'],collected_at=datetime.now(UTC),document_kind=DocumentKind.HTML,access_status=AccessStatus.CONFIRMED_PUBLIC,usage_terms_checked=True,usage_basis='조달청 나라장터 공개 OpenAPI 이용허락범위 제한 없음',notice_number=no,published_at=datetime.fromisoformat(item['bidNtceDt']))
        fields=[('공고 개요',f"공고번호: {no}\n공고명: {m.title}\n공고기관: {item['ntceInsttNm']}\n수요기관: {item.get('dminsttNm','')}"),('일정',f"참가자격 등록: {item.get('bidQlfctRgstDt','')}\n입찰 시작: {item.get('bidBeginDt','')}\n입찰 마감: {item.get('bidClseDt','')}\n개찰: {item.get('opengDt','')}"),('계약·평가',f"계약방법: {item.get('cntrctCnclsMthdNm','')}\n낙찰방법: {item.get('sucsfbidMthdNm','')}\n기초금액: {item.get('presmptPrce','')}\n가격평가비율: {item.get('bidPrceEvlRt','')}")]
        manifests.append(m); chunks.extend(build_chunks(m,[ParsedBlock(None,text,'text','g2b-openapi',0.99,section) for section,text in fields]))
    (root/'data'/'g2b-service-manifest.json').write_text(json.dumps([m.model_dump(mode='json') for m in manifests],ensure_ascii=False,indent=2),encoding='utf8'); (root/'data'/'g2b-service-chunks.json').write_text(json.dumps([c.model_dump(mode='json') for c in chunks],ensure_ascii=False,indent=2),encoding='utf8'); print(json.dumps({'documents':len(manifests),'chunks':len(chunks)},ensure_ascii=False))
if __name__=='__main__': main()
