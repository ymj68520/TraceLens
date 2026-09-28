// Preload with NODE_OPTIONS=--require=<this file> for isolated Node HTTP tests.
// A private network namespace remains mandatory for subprocesses/native code.
const fs = require('node:fs');
const http = require('node:http');
const https = require('node:https');
const net = require('node:net');
const tls = require('node:tls');

class IsolationViolation extends Error {}
const mode = process.env.TRACELENS_TEST_MODE;
const instanceId = process.env.TRACELENS_TEST_INSTANCE_ID || '';
const originText = process.env.TRACELENS_TEST_ORIGIN || '';
if (mode !== 'ISOLATED_TEST' || instanceId.length < 16 ||
    fs.readlinkSync('/proc/self/ns/net') === fs.readlinkSync('/proc/1/ns/net')) {
  throw new IsolationViolation('Node test requires a named synthetic instance in a private network namespace');
}
if (['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']
  .some((key) => process.env[key])) {
  throw new IsolationViolation('proxy environment is forbidden in isolated tests');
}
let origin;
try { origin = new URL(originText); } catch { throw new IsolationViolation('invalid synthetic origin'); }
if (origin.protocol !== 'http:' || origin.hostname !== '127.0.0.1' || !origin.port ||
    origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) {
  throw new IsolationViolation('synthetic origin must be exact http://127.0.0.1:<port>');
}
const allowedOrigin = origin.origin;

function requireUrl(url) {
  let parsed;
  try { parsed = new URL(url); } catch { throw new IsolationViolation('invalid request target'); }
  if (parsed.origin !== allowedOrigin || parsed.username || parsed.password || parsed.protocol !== 'http:') {
    throw new IsolationViolation('request target is not the selected synthetic instance');
  }
}

function requireSocket(args) {
  const first = Array.isArray(args[0]) ? args[0][0] : args[0];
  if (typeof first === 'string' && !/^\d+$/.test(first)) throw new IsolationViolation('Unix sockets are not allowed');
  const options = typeof first === 'object' && first !== null ? first :
    { port: first, host: typeof args[1] === 'string' ? args[1] : undefined };
  if (Number(options.port) !== Number(origin.port) ||
      (options.host || options.hostname || 'localhost') !== '127.0.0.1') {
    throw new IsolationViolation('socket target is not the selected synthetic instance');
  }
}

function requestUrl(args) {
  const first = args[0];
  if (typeof first === 'string' || first instanceof URL) return String(first);
  const options = first || {};
  return `http://${options.hostname || options.host || 'localhost'}:${options.port || 80}${options.path || '/'}`;
}

const originalHttpRequest = http.request;
const originalHttpGet = http.get;
http.request = function (...args) { requireUrl(requestUrl(args)); return originalHttpRequest.apply(this, args); };
http.get = function (...args) { requireUrl(requestUrl(args)); return originalHttpGet.apply(this, args); };
https.request = function () { throw new IsolationViolation('HTTPS target is outside the isolated HTTP instance'); };
https.get = https.request;
const originalSocketConnect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) { requireSocket(args); return originalSocketConnect.apply(this, args); };
tls.connect = function () { throw new IsolationViolation('TLS target is outside the isolated HTTP instance'); };
const originalFetch = globalThis.fetch;
globalThis.fetch = function (url, ...args) { requireUrl(String(url)); return originalFetch.call(this, url, ...args); };

globalThis.__tracelensIsolation = Object.freeze({
  instanceId, origin: allowedOrigin,
  async verifyIdentity() {
    const response = await fetch(allowedOrigin + '/__isolation__/identity');
    if (!response.ok || (await response.json()).instance_id !== instanceId) {
      throw new IsolationViolation('synthetic instance identity mismatch');
    }
  },
});
