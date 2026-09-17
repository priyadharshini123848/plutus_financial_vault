(function(){
  const loader=document.getElementById('page-loader');
  window.addEventListener('load',()=>setTimeout(()=>loader&&loader.classList.add('hide'),450));
  document.addEventListener('click',e=>{const a=e.target.closest('a[href]');if(!a||!a.getAttribute('href').startsWith('/')||a.target==='_blank'||e.ctrlKey||e.metaKey)return;if(a.pathname==='/logout')return;e.preventDefault();if(loader)loader.classList.remove('hide');setTimeout(()=>location.href=a.href,180)});
  const vault=document.getElementById('heroVault');
  const body=vault&&vault.querySelector('.vault-body');
  if(vault&&body){vault.addEventListener('mousemove',e=>{const r=vault.getBoundingClientRect();const x=(e.clientX-r.left)/r.width-.5;const y=(e.clientY-r.top)/r.height-.5;body.style.transform=`rotateY(${x*18}deg) rotateX(${-y*12}deg) translateZ(4px)`});vault.addEventListener('mouseleave',()=>body.style.transform='rotateY(0) rotateX(0) translateZ(0)');vault.addEventListener('click',()=>{body.classList.toggle('open-vault');const door=document.getElementById('vaultDoor');if(door){door.style.transform=body.classList.contains('open-vault')?'translateZ(35px) rotateY(-18deg)':'translateZ(35px) rotateY(0deg)'}})}
  const steps=[...document.querySelectorAll('.security-step')];
  if(steps.length){const obs=new IntersectionObserver(entries=>{if(entries.some(x=>x.isIntersecting)){steps.forEach((s,i)=>setTimeout(()=>s.classList.add('active'),i*180))}},{threshold:.35});const sec=document.getElementById('securitySequence');if(sec)obs.observe(sec)}
  const reveals=[...document.querySelectorAll('.reveal')];if(reveals.length){const obs=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting)e.target.style.animationPlayState='running'}),{threshold:.12});reveals.forEach(x=>{x.style.animationPlayState='paused';obs.observe(x)})}
})();
function toggleMenu(){const n=document.querySelector('.nav-links');if(n)n.classList.toggle('open')}
function cleanText(s){return s.replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
function quickAI(text){const i=document.getElementById('q');if(i){i.value=text;askAI()}}
function askAI(){const i=document.getElementById('q'),m=document.getElementById('messages');if(!i||!m)return;const q=i.value.trim();if(!q)return;m.innerHTML+=`<div class="me-message">${cleanText(q)}</div>`;const x=q.toLowerCase();let a='I can explain the Plutus dashboard, transactions, goals and basic saving concepts.';if(x.includes('save')||x.includes('saving'))a='A simple approach is to set a clear savings target, automate regular contributions and review recurring expenses.';else if(x.includes('dashboard'))a='The dashboard summarizes your balance, account type, recent transactions and financial goals.';else if(x.includes('goal'))a='Create a goal with a target amount. The progress bar shows saved amount compared with the target.';else if(x.includes('transaction'))a='Transactions let you record deposits and withdrawals. Your balance updates when a valid transaction is saved.';m.innerHTML+=`<div class="bot-message">${a}</div>`;i.value='';m.scrollTop=m.scrollHeight}


function toggleTransfer(){
  const type=document.getElementById('txType');
  const box=document.getElementById('transferBox');
  if(type && box){ box.style.display=type.value==='transfer'?'block':'none'; }
}
