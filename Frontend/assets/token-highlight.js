// Token type string to integer mapping
// Unknown types fallback to 0
const TOKEN_TYPES = {
  keyword: 1,
  string: 2,
  comment: 3,
  number: 4,
  literal: 5,
  built_in: 6,
  type: 7,
  function: 8,
  title: 9,
  params: 10,
  variable: 11,
  attr: 12,
  attribute: 13,
  meta: 14,
  operator: 15,
  punctuation: 16,
  regexp: 17,
  symbol: 18,
  class: 19,
  property: 20,
  doctag: 21,
  'template-tag': 22,
  'template-variable': 23,
  subst: 24,
  section: 25,
  'selector-tag': 26,
  'selector-id': 27,
  'selector-class': 28,
  tag: 29,
  name: 30,
  addition: 31,
  deletion: 32,
  emphasis: 33,
  strong: 34,
  link: 35,
  quote: 36,
  code: 37,
  bullet: 38,
  formula: 39,
  char: 40,
  'char.escape': 41,
};

/**
 * Get the numeric token type for a scope string.
 * Handles compound scopes like "title.function" by using the first segment.
 * Returns 0 for unknown types.
 */
function getTokenType(scope) {
  if (!scope) return 0;

  // First try the full scope name
  if (TOKEN_TYPES[scope] !== undefined) {
    return TOKEN_TYPES[scope];
  }

  // For compound scopes like "title.function", try the first segment
  const firstSegment = scope.split('.')[0];
  if (TOKEN_TYPES[firstSegment] !== undefined) {
    return TOKEN_TYPES[firstSegment];
  }

  // Unknown type
  return 0;
}

class PositionEmitter {
  constructor(options) {
    this.options = options;
    this.tokens = [];      // Flat array: [start, end, type, ...]
    this.position = 0;     // Current character position
    this.scopeStack = [];  // Track nested scopes
    this.root = { children: [] };
    this.stack = [this.root];
  }

  addText(text) {
    if (text === '') return;

    const start = this.position;
    const end = start + text.length;

    // Record token if we're inside a scope
    if (this.scopeStack.length > 0) {
      const scopeName = this.scopeStack[this.scopeStack.length - 1];
      const typeId = getTokenType(scopeName);
      this.tokens.push(start, end, typeId);
    }

    this.position = end;
    this.stack[this.stack.length - 1].children.push(text);
  }

  startScope(scope) {
    this.scopeStack.push(scope);
    const node = { scope, children: [] };
    this.stack[this.stack.length - 1].children.push(node);
    this.stack.push(node);
  }

  endScope() {
    this.scopeStack.pop();
    this.stack.pop();
  }

  openNode(scope) {
    this.scopeStack.push(scope);
    const node = { scope, children: [] };
    this.stack[this.stack.length - 1].children.push(node);
    this.stack.push(node);
  }

  closeNode() {
    this.scopeStack.pop();
    this.stack.pop();
  }

  __addSublanguage(emitter, name) {
    const node = emitter.root;
    if (name) node.scope = `language:${name}`;
    this.stack[this.stack.length - 1].children.push(node);

    // The sublanguage is highlighted by a fresh emitter whose positions are
    // relative to the sublanguage buffer, and its text never flows through
    // this emitter's addText — so its tokens must be offset to our current
    // position, and our position must advance past the buffer, or every
    // token from here on lands shifted left.
    const base = this.position;
    for (let i = 0; i < emitter.tokens.length; i += 3) {
      this.tokens.push(
        base + emitter.tokens[i],
        base + emitter.tokens[i + 1],
        emitter.tokens[i + 2]
      );
    }
    this.position += emitter.position;
  }

  toHTML() {
    // Not used for our purposes, but required by the API
    return '';
  }

  finalize() {
    // Close all open nodes
    while (this.stack.length > 1) {
      this.stack.pop();
    }
    return true;
  }
}

// Configure highlight.js to use our custom emitter
hljs.configure({
  __emitter: PositionEmitter
});

/**
 * Parse code and return token positions as a flat array of integers.
 *
 * @param {string} code - The source code to parse
 * @param {Object} options - Options object
 * @param {string} options.language - The language to use for highlighting
 * @returns {number[]} Flat array of [start, end, type] triplets
 */
function highlightTokens(code, language) {
  // Fall back to plaintext if the language is not registered in the bundle
  var lang = language || 'plaintext';
  if (lang !== 'plaintext' && !hljs.getLanguage(lang)) {
    lang = 'plaintext';
  }

  const result = hljs.highlight(code, {
    language: lang,
    ignoreIllegals: true
  });

  // Access the emitter's token data
  return JSON.stringify(result._emitter.tokens);
}
