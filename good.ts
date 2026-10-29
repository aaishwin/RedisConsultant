const input = '{"ok":true}';
let value: unknown;
try {
  value = JSON.parse(input);
} catch {
  value = undefined;
}
export { value };
