/**
 * 老手机浏览器的运行时补齐 —— **必须是 entry.ts 的第一条 import**。
 *
 * @noble/* v2 在**模块加载期**就会调用 `Object.hasOwn`：noble-curves 的
 * `validateObject` 在构造 x25519 实例时执行，而这个 API 要到 Chrome 93 /
 * Safari 15.4 / Firefox 93 才有。缺了它，整个 bundle 在加载那一刻就抛
 * `TypeError`，全局 `sodium` 根本不会定义 —— 页面里 `await sodium.ready`
 * 随即炸掉，手机端整页不可用（iOS 15.3 及更早、老版微信 XWeb 等）。
 *
 * esbuild 的 `--target=es2020` 只降**语法**、不补**运行时 API**，所以必须
 * 自己补。补上之后，加载期不再依赖任何 ES2021+ 的内置对象。
 *
 * 放在独立模块而不是 entry.ts 正文：ESM 的 import 会被提升，模块体里的
 * 语句一定晚于所有 import 执行 —— 只有「第一条 import」能保证执行时序。
 * 删掉这条 import，tests/test_js_crypto.py 里「缺 Object.hasOwn 仍能加载」
 * 的用例会立刻变红。
 */

type HasOwnFn = (target: object, key: PropertyKey) => boolean;

const objectCtor = Object as unknown as { hasOwn?: HasOwnFn };

if (typeof objectCtor.hasOwn !== 'function') {
  Object.defineProperty(Object, 'hasOwn', {
    value: (target: object, key: PropertyKey): boolean =>
      Object.prototype.hasOwnProperty.call(target, key),
    writable: true,
    enumerable: false,
    configurable: true,
  });
}
