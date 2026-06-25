// מחרוזת ה-CSS המוטמעת של דף הנחיתה (מחלקות bx-*), נשמרת 1:1 מעיצוב המקור.

export const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Fredoka:wght@500;600;700&family=Heebo:wght@400;500;600;700;800&family=Rubik:wght@500;600;700;800&display=swap');

.bx-page{position:relative;font-family:'Heebo',system-ui,sans-serif;background:#f6f3eb;color:#1b3a28;overflow-x:hidden;}

/* גילוי בגלילה — החלקה עדינה מהצדדים */
.reveal{opacity:0;transition:opacity .85s cubic-bezier(.16,.8,.3,1),transform .85s cubic-bezier(.16,.8,.3,1);will-change:opacity,transform;}
.reveal-right{transform:translateX(54px);}
.reveal-left{transform:translateX(-54px);}
.reveal-up{transform:translateY(36px);}
.reveal.is-visible{opacity:1;transform:none;}

/* כרטיס בסיס — גוון שנהב חם (לא לבן) */
.bx-card-tile{background:linear-gradient(160deg,#fcf9f2,#f4efe2);border:1px solid #e8e0cf;border-radius:22px;
  box-shadow:0 12px 30px rgba(70,60,35,.07);
  transition:transform .45s cubic-bezier(.16,.8,.3,1),box-shadow .45s,border-color .45s;}

/* ---------- HERO ---------- */
.bx-hero{position:relative;min-height:100vh;display:flex;flex-direction:column;overflow:hidden;isolation:isolate;}
.bx-blob{position:absolute;top:-10%;left:-6%;width:55%;height:80%;z-index:-1;pointer-events:none;background:radial-gradient(closest-side,rgba(79,160,70,.16),transparent 75%);filter:blur(8px);}
.bx-brand{display:flex;align-items:center;justify-content:space-between;padding:22px 40px;}
.bx-logo{display:flex;align-items:center;gap:11px;}
.bx-logo-img{height:160px;width:auto;display:block;}
.bx-footer-brand .bx-logo-img{height:64px;}
.bx-logo-mark{display:grid;place-items:center;width:40px;height:40px;border-radius:13px;background:linear-gradient(145deg,#5cb04e,#3f9a39);box-shadow:0 6px 16px rgba(63,154,57,.28);}
.bx-logo-text{display:flex;flex-direction:column;line-height:1.05;}
.bx-logo-text strong{font-family:'Rubik';font-weight:800;font-size:19px;color:#1b3a28;}
.bx-logo-text small{font-size:11.5px;color:#7c8a7f;}
.bx-nav-cta{font-size:14px;font-weight:700;color:#2c5a3c;text-decoration:none;padding:9px 18px;border:1.5px solid #d3cdbd;border-radius:999px;background:transparent;transition:.2s;}
.bx-nav-cta:hover{border-color:#bcd9b8;color:#2f7a44;background:rgba(63,154,57,.06);}
.bx-main{flex:1;display:flex;align-items:center;justify-content:center;gap:54px;width:100%;max-width:1180px;margin:0 auto;padding:8px 40px 20px;}
.bx-col-text{flex:1;max-width:560px;}
.bx-eyebrow{display:inline-block;font-size:13px;font-weight:700;color:#3f9a39;letter-spacing:.4px;background:#e7f4e1;padding:6px 13px;border-radius:999px;margin-bottom:18px;}
.bx-headline{margin:0;font-family:'Rubik';font-weight:800;letter-spacing:-.4px;line-height:1.18;font-size:clamp(30px,3.9vw,46px);color:#1b3a28;}
.bx-accent{color:#4aa343;}
.bx-lead-text{margin:20px 0 0;font-size:17px;line-height:1.75;color:#6b776c;max-width:500px;}
.bx-col-phone{flex:none;display:flex;flex-direction:column;align-items:center;}
.bx-phone-wrap{position:relative;}
.bx-tilt{transform-style:preserve-3d;will-change:transform;}
.bx-phone{position:relative;width:252px;height:518px;background:#0e120f;border-radius:42px;padding:9px;box-shadow:-26px 30px 60px rgba(34,52,38,.28),0 0 0 2px #20271f;}
.bx-notch{position:absolute;top:18px;left:50%;transform:translateX(-50%);width:88px;height:23px;background:#000;border-radius:13px;z-index:5;}
.bx-screen{position:relative;width:100%;height:100%;border-radius:33px;overflow:hidden;background:#e6ddd2;display:flex;flex-direction:column;}
.bx-vibrate{animation:bxVibrate .5s ease-in-out 1;}
@keyframes bxVibrate{0%,100%{transform:translateX(0)}33%{transform:translateX(-.4px)}66%{transform:translateX(.4px)}}
.bx-wa-header{display:flex;align-items:center;gap:9px;padding:38px 13px 11px;background:#0a8a5f;flex:none;}
.bx-wa-back{flex:none;opacity:.95;}
.bx-wa-ava{width:33px;height:33px;border-radius:50%;background:#2f9e8c;display:grid;place-items:center;flex:none;}
.bx-wa-id{display:flex;flex-direction:column;line-height:1.25;}
.bx-wa-id strong{font-size:13px;color:#fff;font-weight:700;}
.bx-wa-id span{font-size:11px;color:#cdeee2;}
.bx-wa-body{flex:1;min-height:0;overflow-y:auto;padding:14px 12px;display:flex;flex-direction:column;gap:9px;background-color:#e6ddd2;background-image:radial-gradient(rgba(0,0,0,.03) 1px,transparent 1px);background-size:18px 18px;scrollbar-width:none;}
.bx-wa-body::-webkit-scrollbar{display:none;}
.bx-msg{max-width:80%;padding:7px 10px 5px;border-radius:12px;font-size:13.5px;line-height:1.5;position:relative;box-shadow:0 1px 1px rgba(0,0,0,.1);flex:none;}
.bx-msg p{margin:0;color:#0e2118;}
.bx-time{display:block;font-size:9.5px;color:#5b6b64;text-align:start;margin-top:2px;}
.bx-time-user{color:#4f9165;}
.bx-user{align-self:flex-end;background:#d7f3c4;border-top-right-radius:3px;}
.bx-bot{align-self:flex-start;background:#fff;border-top-left-radius:3px;}
.bx-msg-anim{animation:bxMsgIn 2.1s cubic-bezier(.16,.8,.3,1) both;}
@keyframes bxMsgIn{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
.bx-typing{display:flex;gap:4px;align-items:center;padding:11px 12px;}
.bx-typing span{width:7px;height:7px;border-radius:50%;background:#9aa79e;animation:bxType 1.3s infinite;}
@keyframes bxType{0%,60%,100%{transform:translateY(0);opacity:.4}30%{transform:translateY(-3px);opacity:1}}
.bx-wa-input{flex:none;display:flex;align-items:center;gap:7px;padding:8px 10px;background:#e6ddd2;}
.bx-input-pill{flex:1;background:#fff;border-radius:999px;padding:8px 13px;font-size:12px;color:#9aa6a0;}
.bx-send{width:34px;height:34px;border-radius:50%;background:#0a8a5f;display:grid;place-items:center;flex:none;}
.bx-escape{position:absolute;bottom:-28px;left:50%;transform:translateX(-50%);z-index:40;width:max-content;}
.bx-escape-anim{animation:bxEscape 2s cubic-bezier(.16,.8,.3,1) both;}
@keyframes bxEscape{from{opacity:0;transform:translate(-50%,-10px)}to{opacity:1;transform:translate(-50%,0)}}
.bx-escape-bob{animation:bxEscBob 4.5s ease-in-out infinite;}
@keyframes bxEscBob{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}
.bx-escape-bubble{position:relative;background:linear-gradient(150deg,#eafcef,#cdf3da);border-radius:16px;padding:11px 18px;box-shadow:0 16px 34px rgba(63,154,57,.26),0 0 0 1px rgba(63,154,57,.4);}
.bx-escape-bubble p{margin:0;font-family:'Fredoka','Rubik',sans-serif;font-weight:700;font-size:18px;color:#2f8a45;text-align:center;white-space:nowrap;letter-spacing:.2px;}
.bx-escape-bubble::after{content:"";position:absolute;top:-5px;inset-inline-start:50%;margin-inline-start:-6px;width:12px;height:12px;background:#eafcef;transform:rotate(45deg);}
.bx-escape-arrow{display:grid;place-items:center;margin-top:5px;animation:bxArrow 2s ease-in-out infinite;}
@keyframes bxArrow{0%,100%{transform:translateY(0);opacity:.7}50%{transform:translateY(5px);opacity:1}}
.bx-scroll{display:flex;flex-direction:column;align-items:center;gap:2px;padding:6px 0 26px;}
.bx-scroll span{font-size:12.5px;color:#8a958b;}
.bx-chev{animation:bxChev 2.2s ease-in-out infinite;}
@keyframes bxChev{0%,100%{transform:translateY(0);opacity:.5}50%{transform:translateY(6px);opacity:1}}

/* ---------- נתונים ---------- */
.bx-stats{padding:62px 40px 22px;}
.bx-grid4{max-width:1120px;margin:0 auto;display:grid;grid-template-columns:repeat(4,1fr);gap:22px;}
.bx-grid4 > .reveal{display:flex;}
.bx-stat{flex:1;display:flex;flex-direction:column;align-items:center;text-align:center;}
.bx-stat-box{width:100%;display:flex;align-items:center;justify-content:center;padding:18px 12px;}
.bx-stat-num{font-family:'Rubik';font-weight:600;font-size:clamp(38px,4.6vw,56px);color:#878c86;line-height:1;display:inline-flex;align-items:baseline;gap:5px;direction:ltr;}
.bx-stat-unit{font-size:.46em;font-weight:600;color:#a4a99f;}
.bx-stat-static{display:inline-block;}
.bx-stat-label{margin-top:15px;font-size:14.5px;color:#5e6b62;font-weight:600;}

/* ---------- איך זה עובד — רשת 2x2 ---------- */
.bx-hiw{padding:48px 40px 70px;}
.bx-hiw-head{text-align:center;max-width:640px;margin:0 auto 46px;}
.bx-hiw-title{margin:0;font-family:'Rubik';font-weight:800;font-size:clamp(28px,3.6vw,40px);color:#1b3a28;}
.bx-hiw-sub{margin:12px 0 0;font-size:16.5px;color:#6b776c;}
.bx-hiw-grid{max-width:1120px;margin:0 auto;display:grid;grid-template-columns:repeat(3,1fr);gap:26px;}
.bx-hiw-grid > .reveal{display:flex;}
.bx-hcard{flex:1;display:flex;flex-direction:column;align-items:flex-start;text-align:right;padding:28px 28px;}
.bx-hcard:hover{transform:translateY(-4px);box-shadow:0 20px 40px rgba(70,60,35,.13);border-color:#dcebd2;}
.bx-hcard.active{border-color:#cbe6c1;box-shadow:0 18px 40px rgba(63,154,57,.16);}
.bx-node-circle{flex:none;position:relative;width:60px;height:60px;margin-bottom:18px;border-radius:50%;display:grid;place-items:center;background:linear-gradient(150deg,#a6d196,#86c473);box-shadow:0 8px 18px rgba(63,154,57,.2);transition:transform .55s cubic-bezier(.16,.8,.3,1),box-shadow .55s,background .55s;}
.bx-hcard.active .bx-node-circle{background:linear-gradient(150deg,#6cba5b,#3f9a39);transform:scale(1.07);box-shadow:0 14px 26px rgba(63,154,57,.42),0 0 0 7px rgba(92,176,78,.16);}
.bx-hcard:hover .bx-node-circle{transform:scale(1.05);}
.bx-node-badge{position:absolute;top:-4px;left:-4px;width:25px;height:25px;border-radius:50%;background:#1b3a28;color:#fff;font-family:'Rubik';font-weight:700;font-size:12.5px;display:grid;place-items:center;border:3px solid #f7f2e8;transition:background .4s;}
.bx-hcard.active .bx-node-badge{background:#3f9a39;}
.bx-hcard-text{flex:1;}
.bx-hcard-title{font-family:'Rubik';font-weight:700;font-size:18px;color:#1b3a28;margin:0 0 7px;}
.bx-hcard-desc{font-size:14.5px;line-height:1.65;color:#6b776c;margin:0;}

/* ---------- יכולות ---------- */
.bx-feats{padding:34px 40px 96px;}
.bx-feats-head{text-align:center;max-width:680px;margin:0 auto 52px;}
.bx-feats-title{margin:0;font-family:'Rubik';font-weight:800;font-size:clamp(28px,3.6vw,42px);color:#1b3a28;letter-spacing:-.3px;}
.bx-feats-sub{margin:14px 0 0;font-size:16.5px;color:#6b776c;}
.bx-feats-grid{max-width:1120px;margin:0 auto;display:grid;grid-template-columns:repeat(3,1fr);gap:26px;}
.bx-feats-grid > .reveal{display:flex;}
.bx-feat{position:relative;flex:1;display:flex;flex-direction:column;align-items:flex-start;text-align:right;padding:28px 26px;}
.bx-feat:hover{transform:translateY(-5px);box-shadow:0 24px 46px rgba(70,60,35,.14);border-color:#dcebd2;}
.bx-feat-icon{width:48px;height:48px;border-radius:14px;display:grid;place-items:center;margin-bottom:18px;background:#e7f4e1;color:#2c5a3c;transition:background .4s,color .4s,transform .45s cubic-bezier(.16,.8,.3,1);}
.bx-feat:hover .bx-feat-icon{background:linear-gradient(150deg,#5cb04e,#3f9a39);color:#fff;transform:translateY(-2px);}
.bx-feat-title{font-family:'Rubik';font-weight:700;font-size:18px;color:#1b3a28;margin:0 0 8px;}
.bx-feat-desc{font-size:14.5px;line-height:1.65;color:#6b776c;margin:0;}
.bx-feat-soon{position:absolute;top:20px;left:20px;font-size:11.5px;font-weight:700;color:#3f9a39;background:#e7f4e1;border:1px solid #d2e8c9;padding:4px 11px;border-radius:999px;}

@media (max-width:900px){
  .bx-main{flex-direction:column;gap:38px;padding-top:20px;text-align:center;}
  .bx-col-text{max-width:560px;}
  .bx-lead-text{margin-inline:auto;}
}

/* ---------- תחומים (צבעוני + תמונות מונפשות) ---------- */
.bx-ind{padding:34px 40px 100px;}
.bx-ind-head{text-align:center;max-width:680px;margin:0 auto 52px;}
.bx-ind-title{margin:0;font-family:'Rubik';font-weight:800;font-size:clamp(28px,3.6vw,42px);color:#1b3a28;letter-spacing:-.3px;}
.bx-ind-sub{margin:14px 0 0;font-size:16.5px;color:#6b776c;}
.bx-ind-grid{max-width:1120px;margin:0 auto;display:flex;flex-wrap:wrap;justify-content:center;gap:26px;}
.bx-ind-grid > .reveal{display:flex;flex:0 1 330px;min-width:270px;max-width:350px;}
.bx-uc{flex:1;display:flex;flex-direction:column;padding:0;overflow:hidden;text-align:right;}
.bx-uc:hover{transform:translateY(-5px);box-shadow:0 24px 46px rgba(70,60,35,.14);border-color:#dcebd2;}
.bx-uc-img{position:relative;height:138px;overflow:hidden;display:grid;place-items:center;}
.bx-uc-img svg{width:74%;height:78%;position:relative;z-index:1;}
.bx-uc-shine{position:absolute;top:-30%;left:-60%;width:45%;height:160%;z-index:2;pointer-events:none;background:linear-gradient(90deg,transparent,rgba(255,255,255,.5),transparent);transform:rotate(18deg);animation:ucShine 6s ease-in-out infinite;}
@keyframes ucShine{0%{left:-60%}55%,100%{left:140%}}
.bx-uc-body{padding:20px 22px 24px;}
.bx-uc-title{font-family:'Rubik';font-weight:700;font-size:17.5px;margin:0 0 7px;}
.bx-uc-desc{font-size:14px;line-height:1.6;color:#6b776c;margin:0;}

/* ערכות צבע לתמונות */
.bx-uc-mint{background:linear-gradient(150deg,#e6f7f1,#cdeee1);color:#1f9d86;}
.bx-uc-rose{background:linear-gradient(150deg,#fdeef3,#f8dbe6);color:#d65b86;}
.bx-uc-blue{background:linear-gradient(150deg,#e9f1fd,#d4e5fb);color:#3a6fc0;}
.bx-uc-amber{background:linear-gradient(150deg,#fdf3e4,#f9e2c2);color:#cf8a26;}
.bx-uc-violet{background:linear-gradient(150deg,#f1ecfb,#e2d6f7);color:#7458c4;}
.bx-th-mint .bx-uc-title{color:#1f9d86;}
.bx-th-rose .bx-uc-title{color:#d65b86;}
.bx-th-blue .bx-uc-title{color:#3a6fc0;}
.bx-th-amber .bx-uc-title{color:#cf8a26;}
.bx-th-violet .bx-uc-title{color:#7458c4;}

/* אנימציות לתמונות */
.bx-flo{animation:ucFlo 4.5s ease-in-out infinite;}
.bx-flo2{animation:ucFlo 5.2s ease-in-out infinite reverse;}
@keyframes ucFlo{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}
.bx-beat{animation:ucBeat 2.6s ease-in-out infinite;}
@keyframes ucBeat{0%,100%{transform:scale(1)}18%{transform:scale(1.12)}30%{transform:scale(1)}45%{transform:scale(1.07)}60%{transform:scale(1)}}
.bx-draw{stroke-dasharray:180;stroke-dashoffset:180;animation:ucDraw 2.6s ease-in-out infinite;}
@keyframes ucDraw{0%{stroke-dashoffset:180;opacity:.25}45%{opacity:1}70%,100%{stroke-dashoffset:0;opacity:1}}
.bx-spin{animation:ucSpin 9s linear infinite;}
@keyframes ucSpin{to{transform:rotate(360deg)}}
.bx-sway{animation:ucSway 4s ease-in-out infinite;}
@keyframes ucSway{0%,100%{transform:rotate(-6deg)}50%{transform:rotate(6deg)}}
.bx-twk{animation:ucTwk 2.4s ease-in-out infinite;}
.bx-twk2{animation:ucTwk 2.4s ease-in-out infinite .8s;}
@keyframes ucTwk{0%,100%{opacity:.35;transform:scale(.82)}50%{opacity:1;transform:scale(1)}}
.bx-glow{animation:ucGlow 3s ease-in-out infinite;}
@keyframes ucGlow{0%,100%{opacity:.12;transform:scale(.92)}50%{opacity:.3;transform:scale(1.05)}}

/* ---------- מסלולים (Pricing) ---------- */
.bx-pricing{padding:34px 40px 16px;}
.bx-pricing-head{text-align:center;max-width:640px;margin:0 auto 50px;}
.bx-pricing-title{margin:0;font-family:'Rubik';font-weight:800;font-size:clamp(28px,3.6vw,42px);color:#1b3a28;letter-spacing:-.3px;}
.bx-pricing-sub{margin:14px 0 0;font-size:16.5px;color:#6b776c;}
.bx-pricing-grid{max-width:1080px;margin:0 auto;display:grid;grid-template-columns:repeat(3,1fr);gap:24px;align-items:stretch;}
.bx-pricing-grid > .reveal{display:flex;}
.bx-plan{flex:1;display:flex;flex-direction:column;padding:30px 28px;text-align:right;}
.bx-plan-pop{border:2px solid #3f9a39;box-shadow:0 22px 50px rgba(63,154,57,.20);transform:translateY(-10px);}
.bx-plan-top{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:30px;}
.bx-plan-name{margin:0;font-family:'Rubik';font-weight:800;font-size:21px;color:#1b3a28;}
.bx-plan-badge{background:#e7f4e1;color:#3f9a39;font-weight:700;font-size:12px;padding:5px 12px;border-radius:999px;white-space:nowrap;}
.bx-plan-price{margin-top:16px;padding-bottom:22px;border-bottom:1px solid #eadfce;}
.bx-plan-price-row{display:flex;align-items:baseline;gap:7px;}
.bx-plan-amt{font-family:'Rubik';font-weight:800;font-size:clamp(34px,3.3vw,44px);color:#1b3a28;direction:ltr;}
.bx-plan-per{font-size:14px;color:#8a958b;font-weight:600;}
.bx-plan-was{font-size:16px;color:#8a958b;font-weight:600;text-decoration:line-through;direction:ltr;}
.bx-plan-note{margin-top:6px;font-size:13px;color:#3f9a39;font-weight:700;}
.bx-plan-annual{margin-top:4px;font-size:13px;color:#8a958b;font-weight:600;}
.bx-plan-feats{list-style:none;margin:22px 0;padding:0;display:flex;flex-direction:column;gap:13px;flex:1;}
.bx-plan-feats li{display:flex;align-items:flex-start;gap:9px;font-size:14.5px;color:#46524a;line-height:1.5;}
.bx-plan-feats svg{flex:none;margin-top:1px;}
.bx-plan-cta{margin-top:auto;display:block;text-align:center;font-family:'Rubik';font-weight:700;font-size:15.5px;padding:13px;border-radius:13px;text-decoration:none;border:1.5px solid #d3cdbd;color:#2c5a3c;background:transparent;transition:transform .2s,box-shadow .2s,background .2s,border-color .2s;}
.bx-plan-cta:hover{border-color:#bcd9b8;background:rgba(63,154,57,.06);}
.bx-plan-cta.pop{background:linear-gradient(145deg,#58af4c,#3f9a39);color:#fff;border-color:transparent;box-shadow:0 12px 26px rgba(63,154,57,.3);}
.bx-plan-cta.pop:hover{transform:translateY(-2px);box-shadow:0 18px 36px rgba(63,154,57,.44);}

/* ---------- שאלות נפוצות (FAQ) ---------- */
.bx-faq{padding:8px 40px 96px;}
.bx-faq-head{text-align:center;margin:0 auto 30px;}
.bx-faq-title{margin:0;font-family:'Rubik';font-weight:800;font-size:clamp(28px,3.6vw,42px);color:#1b3a28;letter-spacing:-.3px;}
.bx-faq-list{max-width:820px;margin:0 auto;display:flex;flex-direction:column;gap:14px;}
.bx-faq-list > .reveal{display:block;}
.bx-faq-item{padding:0;overflow:hidden;}
.bx-faq-item.open{border-color:#cbe6c1;box-shadow:0 14px 32px rgba(63,154,57,.12);}
.bx-faq-q{width:100%;background:transparent;border:none;cursor:pointer;display:flex;align-items:center;justify-content:space-between;gap:14px;padding:20px 26px;text-align:right;font-family:'Rubik';font-weight:700;font-size:17px;color:#1b3a28;}
.bx-faq-q span{flex:1;}
.bx-faq-chev{flex:none;transition:transform .35s cubic-bezier(.16,.8,.3,1);}
.bx-faq-item.open .bx-faq-chev{transform:rotate(180deg);}
.bx-faq-a-wrap{display:grid;grid-template-rows:0fr;transition:grid-template-rows .4s cubic-bezier(.16,.8,.3,1);}
.bx-faq-item.open .bx-faq-a-wrap{grid-template-rows:1fr;}
.bx-faq-a{overflow:hidden;}
.bx-faq-a p{margin:0;padding:0 26px 22px;font-size:15px;line-height:1.75;color:#5e6b62;}

/* ---------- CTA סופי + פוטר ---------- */
.bx-cta-band{position:relative;overflow:hidden;background:linear-gradient(135deg,#5cb04e 0%,#3f9a39 58%,#34882f 100%);padding:84px 40px;text-align:center;}
.bx-cta-deco{position:absolute;border-radius:50%;background:rgba(255,255,255,.09);z-index:1;pointer-events:none;}
.bx-cta-inner{position:relative;z-index:2;max-width:680px;margin:0 auto;}
.bx-cta-band h2{margin:0;font-family:'Rubik';font-weight:800;font-size:clamp(30px,4vw,46px);color:#fff;letter-spacing:-.3px;}
.bx-cta-band p{margin:16px 0 0;font-size:17px;color:rgba(255,255,255,.92);line-height:1.6;}
.bx-cta-white{display:inline-flex;margin-top:32px;align-items:center;gap:9px;font-family:'Rubik';font-weight:700;font-size:16.5px;color:#2f7a2a;background:#fff;padding:15px 34px;border-radius:14px;text-decoration:none;box-shadow:0 16px 36px rgba(20,40,15,.22);transition:transform .22s,box-shadow .22s;}
.bx-cta-white:hover{transform:translateY(-3px);box-shadow:0 24px 48px rgba(20,40,15,.3);}

.bx-footer{background:#f1ede2;border-top:1px solid #e7e0d2;padding:34px 40px 26px;}
.bx-footer-inner{max-width:1120px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;gap:22px;flex-wrap:wrap;}
.bx-footer-brand{display:flex;align-items:center;gap:11px;}
.bx-footer-name{display:flex;flex-direction:column;line-height:1.05;}
.bx-footer-name strong{font-family:'Rubik';font-weight:800;font-size:18px;color:#1b3a28;}
.bx-footer-name small{font-size:11.5px;color:#7c8a7f;}
.bx-footer-links{display:flex;gap:24px;flex-wrap:wrap;}
.bx-footer-links a{font-size:14px;color:#6b776c;text-decoration:none;transition:color .2s;}
.bx-footer-links a:hover{color:#3f9a39;}
.bx-footer-bottom{max-width:1120px;margin:22px auto 0;padding-top:18px;border-top:1px solid #e7e0d2;text-align:center;font-size:13px;color:#8a958b;}

@media (max-width:960px){
  .bx-hiw-grid,.bx-feats-grid{grid-template-columns:repeat(2,1fr);}
}
@media (max-width:720px){
  .bx-stats{padding:36px 16px 14px;}
  .bx-grid4{gap:10px;}
  .bx-stat-box{padding:22px 8px;}
  .bx-stat-num{font-size:clamp(22px,7vw,40px);}
  .bx-stat-label{font-size:11px;margin-top:10px;}
  .bx-hiw{padding:30px 16px 56px;}
  .bx-hiw-grid{gap:16px;}
  .bx-hcard{padding:22px 20px;}
  .bx-node-circle{width:54px;height:54px;margin-bottom:14px;}
  .bx-node-circle svg{width:24px;height:24px;}
  .bx-hcard-title{font-size:16px;}
  .bx-hcard-desc{font-size:13.5px;}
  .bx-feats{padding:24px 16px 72px;}
  .bx-feat{padding:22px 20px;}
}
@media (max-width:880px){
  .bx-pricing-grid{grid-template-columns:1fr;max-width:430px;}
  .bx-plan-pop{transform:none;}
}
@media (max-width:600px){
  .bx-hiw-grid,.bx-feats-grid{grid-template-columns:1fr;}
  .bx-footer-inner{flex-direction:column;align-items:center;text-align:center;gap:18px;}
  .bx-cta-band{padding:64px 24px;}
}
@media (prefers-reduced-motion:reduce){
  .reveal{opacity:1!important;transform:none!important;transition:none!important;}
  .bx-escape-bob,.bx-chev,.bx-escape-arrow{animation:none!important;}
  .bx-flo,.bx-flo2,.bx-beat,.bx-draw,.bx-spin,.bx-sway,.bx-twk,.bx-twk2,.bx-glow,.bx-uc-shine{animation:none!important;}
  .bx-msg-anim{animation:none!important;}
  .bx-escape-anim{animation:none!important;opacity:1!important;transform:translateX(-50%)!important;}
}
`
