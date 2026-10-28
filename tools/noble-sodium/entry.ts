/**
 * 构建入口 —— 本目录的唯一真源。
 *
 * 产物：phonemic/resources/sodium.js（IIFE，全局名 sodium）
 * 构建：cd tools/noble-sodium && npm ci && npm run build
 *
 * 对应的 esbuild 参数（见 build.mjs）：
 *   esbuild entry.ts --bundle --format=iife --global-name=sodium \
 *     --target=es2020 --minify --legal-comments=eof --outfile=<产物>
 *
 * ⚠️ 依赖版本由同目录 package.json（精确版本）+ package-lock.json 锁定。
 *    改任何依赖版本或 esbuild 参数都会改变产物字节 —— 必须重跑
 *    `pytest tests/test_js_crypto.py`（与 PC 端 PyNaCl 双向对拉）再签入
 *    sodium.js，不能只看「构建成功」。
 *
 * 基线实现是 @serenity-kit/noble-sodium（@noble/* 之上的 libsodium 兼容层）。
 * 注意两个坑：
 *   1. 包根 "." 只导出 camelCase 原语（cryptoBoxEasy…）。libsodium 同名的
 *      snake_case 包装在 "./wrappers" 子入口里 —— 只 export 包根会只剩 13 个符号。
 *   2. 该包只覆盖 box / sign 两个家族；本项目在用的 afternm、generichash、
 *      scalarmult、xchacha20-poly1305、base64 它都没有，故在本文件补齐。
 *
 * 对外名字与参数顺序严格照 libsodium.js，调用方（crypto_providers.js /
 * mobile.html）不需要任何改动。
 *
 * ⚠️ 浏览器基线与 libsodium.js 的 WASM 版不同：noble 是纯 JS，加载期要求
 *    `Object.hasOwn`（Chrome 93 / Safari 15.4+），compat.ts 已补齐；补完实测
 *    只需 BigInt 与 globalThis → Chrome 67+ / Safari 14+ / Firefox 68+。
 */

// ⚠️ 必须是**第一条 import**（理由见 compat.ts）：ESM 的 import 会被提升，
// 这条晚于 noble 模块执行就失去意义，老浏览器会在加载期整包失败。
import './compat.js';

export * from '@serenity-kit/noble-sodium';
export * from '@serenity-kit/noble-sodium/wrappers';

import { xchacha20poly1305 } from '@noble/ciphers/chacha.js';
import { secretbox } from '@noble/ciphers/salsa.js';
// bytesToUtf8 只在 @noble/ciphers/utils.js 里，@noble/hashes/utils.js 没有（v2.4.0）。
import { bytesToUtf8 } from '@noble/ciphers/utils.js';
import { x25519 } from '@noble/curves/ed25519.js';
import { blake2b } from '@noble/hashes/blake2.js';
import { randomBytes, utf8ToBytes } from '@noble/hashes/utils.js';

/* ------------------------------------------------------------------ *
 * 就绪标志
 * ------------------------------------------------------------------ */

// libsodium 的 ready 是「WASM 加载完成」的 Promise。本实现是纯 JS、无异步
// 初始化，但必须保留：mobile.html 的 SecureClient.init() 第一个 await 就是它。
export const ready: Promise<void> = Promise.resolve();

/* ------------------------------------------------------------------ *
 * XChaCha20-Poly1305 AEAD 常量
 * ------------------------------------------------------------------ */

export const crypto_aead_xchacha20poly1305_ietf_KEYBYTES = 32;
export const crypto_aead_xchacha20poly1305_ietf_NPUBBYTES = 24;
export const crypto_aead_xchacha20poly1305_ietf_ABYTES = 16;

/* ------------------------------------------------------------------ *
 * 随机数 / 哈希 / 标量乘
 * ------------------------------------------------------------------ */

export function randombytes_buf(length: number): Uint8Array {
  return randomBytes(length);
}

/**
 * libsodium 签名是 crypto_generichash(outLen, message, key?)：**输出长度在前**。
 * 与 @noble/hashes 的 blake2b(message, {dkLen}) 参数顺序相反，别写反。
 */
export function crypto_generichash(
  outLen: number,
  message: Uint8Array,
  key?: Uint8Array | null,
): Uint8Array {
  return blake2b(message, { dkLen: outLen, key: key ?? undefined });
}

/** X25519：crypto_scalarmult(私钥, 对方公钥) → 共享密钥。 */
export function crypto_scalarmult(
  privateKey: Uint8Array,
  publicKey: Uint8Array,
): Uint8Array {
  return x25519.getSharedSecret(privateKey, publicKey);
}

/** X25519：由私钥推公钥（libsodium 用这个名字，@noble 叫 getPublicKey）。 */
export function crypto_scalarmult_base(privateKey: Uint8Array): Uint8Array {
  return x25519.getPublicKey(privateKey);
}

/* ------------------------------------------------------------------ *
 * 预共享密钥对称盒（crypto_box_*_afternm）
 * ------------------------------------------------------------------ *
 * afternm = 会话密钥已就绪，跳过 X25519 + HSalsa20，直接 XSalsa20-Poly1305。
 * 本项目会话密钥是 BLAKE2b(sharedSecret) 派生的，正好只需要这一层；
 * 若误用包里的 crypto_box_easy（内含 HSalsa20 KDF），两端会静默不互通。
 */

export function crypto_box_easy_afternm(
  message: Uint8Array,
  nonce: Uint8Array,
  key: Uint8Array,
): Uint8Array {
  return secretbox(key, nonce).seal(message);
}

export function crypto_box_open_easy_afternm(
  ciphertext: Uint8Array,
  nonce: Uint8Array,
  key: Uint8Array,
): Uint8Array {
  return secretbox(key, nonce).open(ciphertext);
}

/* ------------------------------------------------------------------ *
 * XChaCha20-Poly1305 AEAD
 * ------------------------------------------------------------------ *
 * libsodium 签名：
 *   encrypt(message, aad, secretNonce, publicNonce, key)
 *   decrypt(secretNonce, ciphertext, aad, publicNonce, key)
 * secretNonce 恒为 null；返回值只含密文（不含 nonce），线上由调用方前置拼接。
 */

export function crypto_aead_xchacha20poly1305_ietf_encrypt(
  message: Uint8Array,
  aad: Uint8Array | null,
  _secretNonce: Uint8Array | null,
  publicNonce: Uint8Array,
  key: Uint8Array,
): Uint8Array {
  return xchacha20poly1305(key, publicNonce, aad ?? undefined).encrypt(message);
}

export function crypto_aead_xchacha20poly1305_ietf_decrypt(
  _secretNonce: Uint8Array | null,
  ciphertext: Uint8Array,
  aad: Uint8Array | null,
  publicNonce: Uint8Array,
  key: Uint8Array,
): Uint8Array {
  return xchacha20poly1305(key, publicNonce, aad ?? undefined).decrypt(
    ciphertext,
  );
}

/* ------------------------------------------------------------------ *
 * base64 / 字符串
 * ------------------------------------------------------------------ */

// 数值必须与 libsodium 对齐。这些常量由调用方原样回传进 from/to_base64，
// 错一个就会让 url-safe 变体退化成标准字母表（在 base64 里 '+' '/' vs '-_'）。
export const base64_VARIANT_ORIGINAL = 1;
export const base64_VARIANT_ORIGINAL_NO_PADDING = 2;
export const base64_VARIANT_URLSAFE = 3;
export const base64_VARIANT_URLSAFE_NO_PADDING = 4;

const B64_STD = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
const B64_URL = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

function isUrlSafeVariant(variant: number): boolean {
  return (
    variant === base64_VARIANT_URLSAFE ||
    variant === base64_VARIANT_URLSAFE_NO_PADDING
  );
}

function isPaddedVariant(variant: number): boolean {
  return (
    variant === base64_VARIANT_ORIGINAL || variant === base64_VARIANT_URLSAFE
  );
}

// 默认变体与 libsodium.js 一致：base64_VARIANT_ORIGINAL（标准字母表 + padding）。
// 不能沿用「0 = 无 padding」的自造缺省：省略参数的调用方会静默拿到另一种编码，
// 在只有 '+' '/' 或结尾 '=' 的数据上才暴露，极难排查。
export function to_base64(
  bytes: Uint8Array,
  variant = base64_VARIANT_ORIGINAL,
): string {
  const A = isUrlSafeVariant(variant) ? B64_URL : B64_STD;
  const pad = isPaddedVariant(variant);
  let out = '';
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i];
    const b1 = i + 1 < bytes.length ? bytes[i + 1] : 0;
    const b2 = i + 2 < bytes.length ? bytes[i + 2] : 0;
    const n = (b0 << 16) | (b1 << 8) | b2;
    out += A[(n >>> 18) & 63] + A[(n >>> 12) & 63];
    out += i + 1 < bytes.length ? A[(n >>> 6) & 63] : pad ? '=' : '';
    out += i + 2 < bytes.length ? A[n & 63] : pad ? '=' : '';
  }
  return out;
}

// 默认变体同 to_base64（libsodium 的 base64_VARIANT_ORIGINAL）。
export function from_base64(
  input: string,
  variant = base64_VARIANT_ORIGINAL,
): Uint8Array {
  const A = isUrlSafeVariant(variant) ? B64_URL : B64_STD;
  const out: number[] = [];
  let bits = 0;
  let value = 0;
  for (const ch of input) {
    const idx = A.indexOf(ch);
    if (idx < 0) continue; // '=' 与空白一律跳过，兼容带/不带 padding
    value = (value << 6) | idx;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out.push((value >>> bits) & 0xff);
    }
  }
  return new Uint8Array(out);
}

/** libsodium 的 to_string = UTF-8 解码（不带结尾 NUL）。 */
export function to_string(bytes: Uint8Array): string {
  return bytesToUtf8(bytes);
}

/** libsodium 的 from_string = UTF-8 编码。 */
export function from_string(str: string): Uint8Array {
  return utf8ToBytes(str);
}
