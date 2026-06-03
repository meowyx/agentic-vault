/* Login page: password -> JWT. On success, stash the token and go to /app.
   The token lives in sessionStorage (per-tab, cleared when the tab closes) so it
   survives the navigation to the app page; it is never written to disk. */

const pwInput = document.getElementById('password');
const signinBtn = document.getElementById('signinBtn');
const loginErr = document.getElementById('loginErr');
const revealBtn = document.getElementById('reveal');
const loginForm = document.getElementById('loginForm');

async function doLogin(){
  const pw = pwInput.value;
  if(!pw){ loginErr.textContent = 'Enter your password.'; return; }
  signinBtn.disabled = true; loginErr.textContent = '';
  try{
    const resp = await fetch('/login', {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify({password: pw}),   // single local user; username is cosmetic
    });
    if(resp.status === 401){ loginErr.textContent = 'Wrong password.'; return; }
    if(!resp.ok){ loginErr.textContent = 'Login failed (' + resp.status + ').'; return; }
    const data = await resp.json();
    sessionStorage.setItem('av_token', data.token);
    window.location.href = '/app';
  }catch(e){
    loginErr.textContent = 'Cannot reach server.';
  }finally{
    signinBtn.disabled = false;
  }
}

loginForm.addEventListener('submit', e => { e.preventDefault(); doLogin(); });
revealBtn.addEventListener('click', () => {
  pwInput.type = pwInput.type === 'password' ? 'text' : 'password';
});
pwInput.focus();
