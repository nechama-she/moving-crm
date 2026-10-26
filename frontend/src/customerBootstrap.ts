import { registerCustomerSession } from './customerSession';
export function readCustomerBootstrap(accessId: string | undefined) {
  try {
    const node = document.getElementById('move-bootstrap');
    if (!node?.textContent) return null;
    const value = JSON.parse(node.textContent);
    if (value.accessId !== accessId || !value.session || value.expiresAt <= Date.now() || !value.move) return null;
    const storageKey = `cm_session_${accessId}${value.rep ? '_rep' : ''}`;
    sessionStorage.setItem(storageKey, value.session);
    sessionStorage.setItem(storageKey + ':expiresAt', String(value.expiresAt));
    registerCustomerSession(value.session, value.expiresAt);
    return value;
  } catch { return null; }
}
