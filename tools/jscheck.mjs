/**
 * Parse every file, then report every identifier used but declared nowhere.
 *
 *     cd frontend && node ../tools/jscheck.mjs src      (CI runs this)
 *     node tools/jscheck.mjs <file-or-dir> [...]
 *
 * Exits 1 on a parse error or an undefined name, 0 otherwise.
 *
 * Why this exists: Vite treats an undeclared identifier as a global and builds
 * cleanly, so a handler passing a setter that was renamed or never existed
 * builds, deploys, and throws on the first click. ESLint is not a dependency
 * here and adding it would bring a large tree into `npm audit`, so this uses
 * the oxc parser that rolldown (Vite's bundler) already ships and does its own
 * scope analysis.
 *
 * The analysis is deliberately simple. Every declaration anywhere in a scope
 * counts for that whole scope (hoisting and the temporal dead zone are not
 * modelled), `var` goes to its function, `let`/`const`/`class`/function
 * declarations to their block. That can only miss a use-before-declare; it
 * cannot invent an undefined name that is really declared.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROLLDOWN = process.env.JSCHECK_ROLLDOWN
  || path.join(HERE, "..", "frontend", "node_modules", "rolldown", "dist", "parse-ast-index.mjs");
if (!fs.existsSync(ROLLDOWN)) {
  console.error(`rolldown's parser is not at ${ROLLDOWN}; run npm ci in frontend/ first`);
  process.exit(2);
}
const { parseAst } = await import(pathToFileURL(ROLLDOWN).href);

const GLOBALS = new Set(`
  undefined NaN Infinity globalThis self window document navigator location history screen
  console localStorage sessionStorage indexedDB caches crypto performance
  setTimeout clearTimeout setInterval clearInterval requestAnimationFrame cancelAnimationFrame
  queueMicrotask structuredClone requestIdleCallback cancelIdleCallback
  fetch Headers Request Response FormData URL URLSearchParams AbortController AbortSignal
  Blob File FileReader FileList DataTransfer ReadableStream WritableStream TransformStream
  TextEncoder TextDecoder atob btoa encodeURIComponent decodeURIComponent encodeURI decodeURI
  alert confirm prompt open close print scrollTo scrollX scrollY innerWidth innerHeight
  devicePixelRatio visualViewport getComputedStyle matchMedia getSelection
  Event CustomEvent KeyboardEvent MouseEvent PointerEvent FocusEvent WheelEvent TouchEvent
  DragEvent InputEvent ErrorEvent PromiseRejectionEvent StorageEvent MessageEvent
  AnimationEvent TransitionEvent
  EventTarget Node Element HTMLElement HTMLInputElement HTMLTextAreaElement HTMLSelectElement
  HTMLButtonElement HTMLAnchorElement HTMLFormElement HTMLDivElement HTMLCanvasElement
  SVGElement Document Window Text Range Selection NodeFilter TreeWalker DOMParser XMLSerializer
  DOMException DOMRect Image Audio Option CSS
  MutationObserver ResizeObserver IntersectionObserver
  XMLHttpRequest WebSocket EventSource BroadcastChannel MessageChannel Worker Notification
  PublicKeyCredential AuthenticatorAttestationResponse AuthenticatorAssertionResponse
  ClipboardItem CanvasRenderingContext2D Path2D ImageData OffscreenCanvas createImageBitmap
  Math JSON Date Array Object String Number Boolean Symbol BigInt RegExp Map Set WeakMap WeakSet
  WeakRef FinalizationRegistry Promise Proxy Reflect Intl Atomics SharedArrayBuffer
  Error TypeError RangeError SyntaxError ReferenceError EvalError URIError AggregateError
  ArrayBuffer DataView Int8Array Uint8Array Uint8ClampedArray Int16Array Uint16Array
  Int32Array Uint32Array Float32Array Float64Array BigInt64Array BigUint64Array
  isNaN isFinite parseInt parseFloat eval arguments process
`.split(/\s+/).filter(Boolean));

// "value" is NOT skipped: JSXAttribute.value and Property.value hold the arrow
// functions whose parameters must be declared, and a Literal's primitive value
// is dropped anyway because it has no `type`.
const SKIP_KEYS = new Set(["type", "start", "end", "range", "loc", "raw", "regex",
  "bigint", "directive", "kind", "operator", "prefix", "computed", "shorthand", "method",
  "static", "async", "generator", "optional", "sourceType", "hashbang", "comments", "tail",
  "delegate", "await", "exportKind", "importKind", "phase"]);

function children(node) {
  const out = [];
  for (const key of Object.keys(node)) {
    if (SKIP_KEYS.has(key)) continue;
    const v = node[key];
    if (Array.isArray(v)) { for (const x of v) if (x && typeof x.type === "string") out.push([key, x]); }
    else if (v && typeof v.type === "string") out.push([key, v]);
  }
  return out;
}

function bindingNames(pattern, out = []) {
  if (!pattern) return out;
  switch (pattern.type) {
    case "Identifier": out.push(pattern.name); break;
    case "ObjectPattern":
      for (const p of pattern.properties) bindingNames(p.type === "RestElement" ? p.argument : p.value, out);
      break;
    case "ArrayPattern": for (const e of pattern.elements) bindingNames(e, out); break;
    case "AssignmentPattern": bindingNames(pattern.left, out); break;
    case "RestElement": bindingNames(pattern.argument, out); break;
    default: break;
  }
  return out;
}

const FUNCS = new Set(["FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression"]);
const BLOCKS = new Set(["BlockStatement", "ForStatement", "ForInStatement", "ForOfStatement",
  "CatchClause", "SwitchStatement", "StaticBlock", "ClassExpression", "ClassDeclaration"]);

function check(file) {
  const src = fs.readFileSync(file, "utf8");
  let ast;
  try {
    ast = parseAst(src, { lang: /\.tsx?$/.test(file) ? "tsx" : "jsx", sourceType: "module" });
  } catch (err) {
    return [{ file, line: 0, msg: `parse error: ${String(err.message).split("\n").slice(0, 3).join(" ")}` }];
  }
  const lineOf = (pos) => src.slice(0, pos).split("\n").length;

  // Pass A: every scope and what it declares.
  const scopes = new Map();        // node -> {parent, names:Set, fn:boolean}
  function scopeFor(node, parent, fn) {
    const s = { parent, names: new Set(), fn };
    scopes.set(node, s);
    return s;
  }
  const fnScope = (s) => { while (s && !s.fn) s = s.parent; return s; };

  function declare(node, scope) {
    let here = scope;
    if (node === ast) here = scopeFor(node, null, true);
    else if (FUNCS.has(node.type)) {
      if (node.type === "FunctionDeclaration" && node.id) scope.names.add(node.id.name);
      here = scopeFor(node, scope, true);
      if (node.type === "FunctionExpression" && node.id) here.names.add(node.id.name);
      for (const p of node.params) for (const n of bindingNames(p)) here.names.add(n);
    } else if (BLOCKS.has(node.type)) {
      if (node.type === "ClassDeclaration" && node.id) scope.names.add(node.id.name);
      here = scopeFor(node, scope, false);
      if (node.type === "ClassExpression" && node.id) here.names.add(node.id.name);
      if (node.type === "CatchClause" && node.param) for (const n of bindingNames(node.param)) here.names.add(n);
    }
    if (node.type === "ImportDeclaration") {
      for (const sp of node.specifiers) scope.names.add(sp.local.name);
    } else if (node.type === "VariableDeclaration") {
      const target = node.kind === "var" ? fnScope(scope) : scope;
      for (const d of node.declarations) for (const n of bindingNames(d.id)) target.names.add(n);
    }
    for (const [, child] of children(node)) declare(child, here);
  }
  declare(ast, null);

  // Pass B: every identifier in a reference position must resolve.
  const problems = [];
  const seen = new Set();
  function resolves(name, scope) {
    for (let s = scope; s; s = s.parent) if (s.names.has(name)) return true;
    return GLOBALS.has(name);
  }
  function ref(id, scope) {
    if (resolves(id.name, scope)) return;
    const key = `${id.name}@${lineOf(id.start)}`;
    if (seen.has(key)) return;
    seen.add(key);
    problems.push({ file, line: lineOf(id.start), msg: `'${id.name}' is not defined` });
  }
  // Visit a pattern: its names are bindings, but defaults and computed keys are expressions.
  function pattern(p, scope) {
    if (!p) return;
    switch (p.type) {
      case "Identifier": return;
      case "ObjectPattern":
        for (const prop of p.properties) {
          if (prop.type === "RestElement") { pattern(prop.argument, scope); continue; }
          if (prop.computed) walk(prop.key, scope);
          pattern(prop.value, scope);
        }
        return;
      case "ArrayPattern": for (const e of p.elements) pattern(e, scope); return;
      case "AssignmentPattern": pattern(p.left, scope); walk(p.right, scope); return;
      case "RestElement": pattern(p.argument, scope); return;
      default: walk(p, scope);  // e.g. a MemberExpression as an assignment target
    }
  }
  function walk(node, scope) {
    if (!node) return;
    const own = scopes.get(node);
    const s = own || scope;
    switch (node.type) {
      case "Identifier": ref(node, s); return;
      case "ImportDeclaration": return;
      case "ExportNamedDeclaration":
        if (node.declaration) walk(node.declaration, s);
        else if (!node.source) for (const sp of node.specifiers) if (sp.local.type === "Identifier") ref(sp.local, s);
        return;
      case "ExportAllDeclaration": return;
      case "VariableDeclarator": pattern(node.id, s); walk(node.init, s); return;
      case "FunctionDeclaration": case "FunctionExpression": case "ArrowFunctionExpression":
        for (const p of node.params) pattern(p, s);
        walk(node.body, s);
        return;
      case "ClassDeclaration": case "ClassExpression":
        walk(node.superClass, s); walk(node.body, s); return;
      case "CatchClause": pattern(node.param, s); walk(node.body, s); return;
      case "MemberExpression":
        walk(node.object, s);
        if (node.computed) walk(node.property, s);
        return;
      case "Property":
        if (node.computed) walk(node.key, s);
        walk(node.value, s);
        return;
      case "MethodDefinition": case "PropertyDefinition": case "AccessorProperty":
        if (node.computed) walk(node.key, s);
        walk(node.value, s);
        return;
      case "LabeledStatement": walk(node.body, s); return;
      case "BreakStatement": case "ContinueStatement": case "MetaProperty":
      case "PrivateIdentifier": case "Literal": case "TemplateElement": return;
      case "AssignmentExpression": pattern(node.left, s); walk(node.right, s); return;
      case "ForInStatement": case "ForOfStatement":
        if (node.left.type === "VariableDeclaration") walk(node.left, s); else pattern(node.left, s);
        walk(node.right, s); walk(node.body, s);
        return;
      // JSX: a capitalised or dotted element name is a reference; attributes are not.
      case "JSXOpeningElement": case "JSXClosingElement":
        jsxName(node.name, s);
        if (node.attributes) for (const a of node.attributes) walk(a, s);
        return;
      case "JSXAttribute": walk(node.value, s); return;
      case "JSXIdentifier": case "JSXNamespacedName": case "JSXText": return;
      case "JSXMemberExpression": jsxName(node, s); return;
      default:
        for (const [, child] of children(node)) walk(child, s);
    }
  }
  function jsxName(n, scope) {
    if (!n) return;
    if (n.type === "JSXIdentifier") {
      if (/^[A-Z_$]/.test(n.name)) ref({ name: n.name, start: n.start }, scope);
    } else if (n.type === "JSXMemberExpression") {
      let o = n.object;
      while (o.type === "JSXMemberExpression") o = o.object;
      if (o.type === "JSXIdentifier") ref({ name: o.name, start: o.start }, scope);
    }
  }
  walk(ast, null);
  return problems;
}

function expand(p) {
  const st = fs.statSync(p);
  if (!st.isDirectory()) return [p];
  const out = [];
  for (const name of fs.readdirSync(p)) {
    if (name === "node_modules" || name === "dist" || name.startsWith(".")) continue;
    out.push(...expand(path.join(p, name)).filter((f) => fs.statSync(f).isDirectory() || /\.(jsx?|mjs|tsx?)$/.test(f)));
  }
  return out.filter((f) => /\.(jsx?|mjs|tsx?)$/.test(f));
}

const files = process.argv.slice(2).flatMap(expand);
let bad = 0;
for (const f of files) {
  for (const p of check(f)) { bad += 1; console.log(`${p.file}:${p.line}: ${p.msg}`); }
}
console.log(`${files.length} file(s) checked, ${bad} problem(s)`);
process.exit(bad ? 1 : 0);
