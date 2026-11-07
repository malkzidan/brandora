// Dependency-free bridge to Backend's unchanged ai-cross-contract.py.
// Executes inspected function bodies; does not emulate NestJS, PostgreSQL or persistence.
const fs = require('node:fs');
const path = require('node:path');
const cp = require('node:child_process');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const { stripTypeScriptTypes } = require('node:module');
const option = (name) => process.argv[process.argv.indexOf(name) + 1];
const reference = path.resolve(option('--backend-reference'));
const aiDir = path.resolve(__dirname, '..');
const python = path.resolve(option('--python'));
const blobs = {
  'src/ai/ai-security.ts': 'f0f063ed616dcefd33bf24bdfdcd49f071e39213',
  'src/ai/ai-response.ts': '06586cae86f47c9eed5db32471df5639a19da8b1',
  'src/products/product-presenter.ts': 'cd837e5c9706c87f23fabdb91bdb5c9e46166b4b',
  'src/common/pagination/pagination.ts': '230ed8d54bc9d59957ce00df704825fcb3876ddf',
};
function source(file) {
  const text = fs.readFileSync(path.join(reference, file), 'utf8').replace(/\r\n/g, '\n');
  const sha = crypto.createHash('sha1').update('blob ' + Buffer.byteLength(text) + '\0' + text).digest('hex');
  assert.equal(sha, blobs[file], 'Reference must match inspected GitHub blob');
  return text;
}
const strip = (text) => stripTypeScriptTypes(text, { mode: 'strip' }).replace(/\bexport /g, '');
const security = source('src/ai/ai-security.ts');
const issue = security.slice(security.indexOf('  issue(message:'), security.indexOf('  authenticate('));
// Only DI/config access is supplied here; the actual issue method body is unchanged.
const Issuer = new Function('sign', 'digest', strip(`class Issuer {
  config;
  constructor(config) { this.config = config; }
  settings() { return this.config; }
  ${issue}
}`) + '; return Issuer;')(crypto.sign, (body) => crypto.createHash('sha256').update(body).digest('hex'));
const responses = source('src/ai/ai-response.ts').replace(/^import .*;\n/m, '');
const validateAiResponse = new Function(strip(responses) + '; return validateAiResponse;')();
const pagination = source('src/common/pagination/pagination.ts');
const presenter = source('src/products/product-presenter.ts').replace(/import[\s\S]*?from '[^']+';\n/g, '');
const productResponse = new Function(strip(pagination + '\n' + presenter) + '; return productResponse;')();
const ids = {
  businessId: '10000000-0000-4000-8000-000000000001',
  customerId: '30000000-0000-4000-8000-000000000001',
  conversationId: '20000000-0000-4000-8000-000000000001',
  messageId: '40000000-0000-4000-8000-000000000002',
};
const productId = '50000000-0000-4000-8000-000000000001';
const product = productResponse({
  id: productId, businessId: ids.businessId, name: 'black tshirt', description: null,
  basePrice: { toFixed: () => '275.00' }, options: { Size: ['L'] }, attributes: {}, isActive: true,
  images: [{ id: '70000000-0000-4000-8000-000000000001', productId, position: 0,
    secureUrl: 'https://images.example.invalid/fixture.jpg', optionName: null, optionValue: null,
    width: 40, height: 30, bytes: 100, format: 'jpg' }],
  variants: [{ id: '60000000-0000-4000-8000-000000000001', businessId: ids.businessId,
    productId, optionValues: { Size: 'L' }, unitPrice: null, trackInventory: true,
    stockQuantity: 7, isActive: true }], _count: { variants: 1 },
}, true);
const keys = crypto.generateKeyPairSync('rsa', { modulusLength: 2048 });
const issuer = new Issuer({ key: keys.privateKey });
const createdAt = '2026-11-04T10:00:00.000Z';
const history = {
  businessId: ids.businessId, customerId: ids.customerId, conversationId: ids.conversationId,
  beforeMessageId: ids.messageId, beforeMessageCreatedAt: createdAt, snapshot: 'synthetic-snapshot',
  order: 'createdAt_desc_id_desc', complete: true,
  pagination: { limit: 20, offset: 0, totalCount: 1, hasMore: false, nextOffset: null },
  items: [{ id: '40000000-0000-4000-8000-000000000001', conversationId: ids.conversationId,
    senderType: 'CUSTOMER', messageType: 'TEXT', content: 'black tshirt', createdAt: '2026-11-04T09:59:59.000Z' }],
};
const variants = [];
for (const message of ['black tshirt size L price', 'بكام التيشيرت الأسود مقاس L؟', 'black tshirt size L price 🧵']) {
  const body = JSON.stringify({ ...ids, message });
  const input = {
    ids, body, token: issuer.issue({ ...ids, message }, body),
    public: keys.publicKey.export({ type: 'spki', format: 'pem' }).toString(),
    outbound: crypto.randomBytes(48).toString('base64url'),
    inbound: crypto.randomBytes(48).toString('base64url'), product, history,
  };
  const result = cp.spawnSync(python, ['-B', path.join(reference, 'verification/ai-cross-contract.py')], {
    cwd: aiDir, input: JSON.stringify(input), encoding: 'utf8', maxBuffer: 1048576,
    env: { ...process.env, BRANDORA_AI_SOURCE: aiDir, AI_PROVIDER: 'rules', GROQ_API_KEY: '',
      PYTHON_DOTENV_DISABLED: '1', PYTHONDONTWRITEBYTECODE: '1', PYTHONIOENCODING: 'utf-8' },
    windowsHide: true,
  });
  if (result.status !== 0) {
    // Tracebacks can contain fixture credentials; never print child output on failure.
    console.error('Backend Python cross-contract harness failed; input and diagnostics suppressed.');
    process.exit(1);
  }
  const output = JSON.parse(result.stdout.trim());
  validateAiResponse(output.response);
  assert(output.calls.includes('get_products'));
  variants.push({ request: message, calls: output.calls, historyCoverage: output.coverage,
    responseAcceptedByBackend: true });
}
for (const patch of [{ intent: 'CONFIRMED_ORDER' }, { orderCandidate: {} }, { requiresReview: 'true' }, { extra: true }])
  assert.throws(() => validateAiResponse({ intent: 'INQUIRY', reply: 'safe', requiresReview: false,
    orderCandidate: null, ...patch }));
console.log(JSON.stringify({ backendCommit: 'f7c826fc76bc0ab8569ae0ed25106ff19bdaae45',
  kind: 'inspected Backend function bodies + unchanged Python harness; synthetic HTTP transport',
  nodeSignedRequestsAccepted: true, presenterDtoAccepted: true, rawBodyTamperRejected: true,
  wrongDirectionalCredentialRejected: true, backendResponseValidation: true, variants,
  networkRequests: 0, nestJsApplicationExecuted: false, realPostgreSQL: false,
  realConversationPersistence: false, liveGroq: false }, null, 2));
