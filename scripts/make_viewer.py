"""Build a self-contained viewer.html for style renders (images referenced by relative path).

Usage: python make_viewer.py SHOOT_DIR [--images styles]
Looks for <photo>_<style>_1080x1350.jpg in SHOOT_DIR/<images>; writes SHOOT_DIR/viewer.html.
"""
import argparse, glob, json, os

ap = argparse.ArgumentParser(); ap.add_argument('dir'); ap.add_argument('--images', default='styles')
A = ap.parse_args()
here = os.path.dirname(os.path.abspath(__file__))
S = {k: v for k, v in json.load(open(os.path.join(here, 'styles.json'))).items() if not k.startswith('_')}
order = ['original'] + list(S)
labels = {'original': 'Original', **{k: v.get('label', k) for k, v in S.items()}}
photos = {}
for f in sorted(glob.glob(os.path.join(A.dir, A.images, '*_1080x1350.jpg'))):
    stem = os.path.basename(f)[:-len('_1080x1350.jpg')]
    st = next((k for k in sorted(order, key=len, reverse=True) if stem.endswith('_' + k)), None)
    if st: photos.setdefault(stem[:-len(st) - 1], {})[st] = os.path.relpath(f, A.dir)
data = [{'photo': p, 'items': [{'style': k, 'label': labels[k], 'src': d[k]} for k in order if k in d]} for p, d in photos.items()]
if not data: raise SystemExit(f'no *_<style>_1080x1350.jpg files in {os.path.join(A.dir, A.images)}')

PAGE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Style picker</title>
<style>
:root{--bg:#111;--panel:#1b1b1b;--line:#2c2c2c;--fg:#eee;--dim:#999;--acc:#e8c28e}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 -apple-system,system-ui,sans-serif}
header{position:sticky;top:0;z-index:5;display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:12px 16px;background:rgba(17,17,17,.92);border-bottom:1px solid var(--line)}
h1{font-size:15px;font-weight:600;margin:0 auto 0 0}
button,select{background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:6px 10px;font:inherit;cursor:pointer}
button.on{border-color:var(--acc);color:var(--acc)}
main{padding:16px;max-width:1500px;margin:auto}h2{font-size:13px;font-weight:500;color:var(--dim);margin:20px 0 10px;letter-spacing:.04em}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px}
figure{margin:0;cursor:zoom-in}figure img{width:100%;aspect-ratio:4/5;object-fit:cover;border-radius:6px;display:block;background:var(--panel)}
figcaption{padding:6px 2px;color:var(--dim);font-size:12px}
#lb{position:fixed;inset:0;background:rgba(0,0,0,.95);display:none;align-items:center;justify-content:center;flex-direction:column;z-index:10}
#lb.open{display:flex}#lb img{max-width:96vw;max-height:88vh}#lbcap{color:var(--dim);margin-top:10px}
.nav{position:absolute;top:50%;transform:translateY(-50%);font-size:28px;background:none;border:0;padding:20px;color:#bbb}
#prev{left:0}#next{right:0}#close{position:absolute;top:10px;right:14px;font-size:22px;background:none;border:0}
.cmp{display:none;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:12px}.cmp.show{display:flex}
.two{display:grid;grid-template-columns:1fr 1fr;gap:10px}.two img{width:100%;max-height:calc(100vh - 150px);object-fit:contain;border-radius:6px}.two div{color:var(--dim);font-size:12px;padding:4px 2px}
.ba{position:relative;width:min(640px,calc((100vh - 150px)*.8),100%);margin:auto;user-select:none;touch-action:none}.ba img{width:100%;display:block;border-radius:6px}
.ba .top{position:absolute;inset:0;overflow:hidden}.ba .top img{position:absolute;top:0;left:0}
.ba .bar{position:absolute;top:0;bottom:0;width:2px;background:var(--acc);cursor:ew-resize}
.ba .tag{position:absolute;top:8px;padding:2px 8px;background:rgba(0,0,0,.6);border-radius:4px;font-size:12px}
@media(max-width:600px){.grid{grid-template-columns:1fr 1fr}.two{grid-template-columns:1fr}}
</style></head><body>
<header><h1>Pick a style</h1><button data-m="grid" class="on">Grid</button><button data-m="two">Compare</button><button data-m="ba">Before / after</button></header>
<main><div class="cmp" id="ctl"></div><div id="view"></div></main>
<div id="lb"><button id="close">&times;</button><button class="nav" id="prev">&#8249;</button><img id="lbimg" alt=""><div id="lbcap"></div><button class="nav" id="next">&#8250;</button></div>
<script>
const D=__DATA__, flat=D.flatMap(g=>g.items.map(i=>({...i,photo:g.photo})));
const $=s=>document.querySelector(s), view=$('#view'), ctl=$('#ctl');
let mode='grid', idx=0, st={photo:D[0].photo,a:null,b:null};
const opt=(arr,sel)=>arr.map(i=>`<option value="${i.style}"${i.style===sel?' selected':''}>${i.label}</option>`).join('');
const items=()=>D.find(g=>g.photo===st.photo).items, pick=s=>items().find(i=>i.style===s)||items()[0];
function render(){
  document.querySelectorAll('header button').forEach(b=>b.classList.toggle('on',b.dataset.m===mode));
  ctl.classList.toggle('show',mode!=='grid');
  if(mode==='grid'){view.innerHTML=D.map(g=>`<h2>${g.photo}</h2><div class="grid">${g.items.map(i=>
    `<figure data-i="${flat.findIndex(f=>f.src===i.src)}"><img loading="lazy" src="${i.src}" alt="${i.label}"><figcaption>${i.label}</figcaption></figure>`).join('')}</div>`).join('');return}
  const it=items(), a=st.a||(mode==='ba'?'original':it[1]?.style), b=st.b||it[2]?.style||it[0].style;
  ctl.innerHTML=`<select id="ph">${D.map(g=>`<option${g.photo===st.photo?' selected':''}>${g.photo}</option>`).join('')}</select>`+
    (mode==='two'?`<select id="sa">${opt(it,a)}</select><span>vs</span>`:`<span>Original vs</span>`)+`<select id="sb">${opt(it,b)}</select>`;
  $('#ph').onchange=e=>{st={photo:e.target.value,a:null,b:null};render()};
  if($('#sa'))$('#sa').onchange=e=>{st.a=e.target.value;render()};
  $('#sb').onchange=e=>{st.b=e.target.value;render()};
  const A=pick(a), B=pick(b);
  if(mode==='two'){view.innerHTML=`<div class="two"><figure><img src="${A.src}"><div>${A.label}</div></figure><figure><img src="${B.src}"><div>${B.label}</div></figure></div>`;return}
  const O=pick('original');
  view.innerHTML=`<div class="ba" id="ba"><img src="${B.src}" alt=""><div class="top"><img src="${O.src}" alt=""></div><div class="bar"></div>
    <span class="tag" style="left:8px">${O.label}</span><span class="tag" style="right:8px">${B.label}</span></div>`;
  const box=$('#ba'), top=box.querySelector('.top'), bar=box.querySelector('.bar'), timg=top.querySelector('img');
  const set=p=>{top.style.width=p*100+'%';bar.style.left=`calc(${p*100}% - 1px)`;timg.style.width=box.clientWidth+'px'};
  const mv=e=>{const r=box.getBoundingClientRect();set(Math.min(1,Math.max(0,(e.clientX-r.left)/r.width)))};
  box.onpointerdown=e=>{box.setPointerCapture(e.pointerId);mv(e);box.onpointermove=mv};
  box.onpointerup=()=>box.onpointermove=null; onresize=()=>set(parseFloat(top.style.width)/100||.5); set(.5);
}
function show(i){idx=(i+flat.length)%flat.length;const f=flat[idx];$('#lbimg').src=f.src;$('#lbcap').textContent=`${f.photo} · ${f.label}`;$('#lb').classList.add('open')}
view.onclick=e=>{const f=e.target.closest('figure[data-i]');if(f)show(+f.dataset.i)};
$('#prev').onclick=()=>show(idx-1);$('#next').onclick=()=>show(idx+1);$('#close').onclick=()=>$('#lb').classList.remove('open');
$('#lb').onclick=e=>{if(e.target.id==='lb')$('#lb').classList.remove('open')};
onkeydown=e=>{if(!$('#lb').classList.contains('open'))return;if(e.key==='ArrowLeft')show(idx-1);if(e.key==='ArrowRight')show(idx+1);if(e.key==='Escape')$('#lb').classList.remove('open')};
document.querySelectorAll('header button').forEach(b=>b.onclick=()=>{mode=b.dataset.m;st.a=st.b=null;render()});
render();
</script></body></html>'''
out = os.path.join(A.dir, 'viewer.html')
open(out, 'w').write(PAGE.replace('__DATA__', json.dumps(data).replace('</', '<\\/')))
print('wrote', out, f'({len(data)} photos, {sum(len(g["items"]) for g in data)} images)')
