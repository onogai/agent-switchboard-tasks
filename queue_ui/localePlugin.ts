import uk from './src/locales/uk.json'
import es from './src/locales/es-ES.json'
import ts from 'typescript'
import type { Plugin } from 'vite'

/**
 * Translate only presentation nodes in JSX. Never rewrite string literals in
 * callbacks, conditions, URLs, API arguments, form values, status IDs or data.
 * English text is a fallback when a locale lacks a translation.
 */
export function localePlugin(): Plugin {
  const keys = new Set([...Object.keys(uk), ...Object.keys(es)])
  const presentationAttributes = new Set([
    'label', 'title', 'placeholder', 'helperText', 'aria-label',
    'alt', 'emptyLabel', 'description',
  ])
  const makeCall = (value: string): ts.CallExpression =>
    ts.factory.createCallExpression(
      ts.factory.createIdentifier('__tx'), undefined,
      [ts.factory.createStringLiteral(value)],
    )

  // Only literal display values, including the display branches of ternaries.
  // Never descend into condition expressions or arbitrary function calls.
  const presentation = (node: ts.Expression): ts.Expression => {
    if (ts.isStringLiteral(node) && keys.has(node.text)) return makeCall(node.text)
    if (ts.isParenthesizedExpression(node)) {
      return ts.factory.updateParenthesizedExpression(node, presentation(node.expression))
    }
    if (ts.isConditionalExpression(node)) {
      return ts.factory.updateConditionalExpression(
        node, node.condition, node.questionToken,
        presentation(node.whenTrue), node.colonToken, presentation(node.whenFalse),
      )
    }
    return node
  }

  return {
    name: 'switchboard-locale-catalogs',
    enforce: 'pre',
    transform(code, id) {
      const file = id.split('?')[0]
      if (!file.endsWith('.tsx') || !file.includes('/src/')) return null
      const source = ts.createSourceFile(file, code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
      let replaced = 0
      const transformer: ts.TransformerFactory<ts.SourceFile> = context => root => {
        const visit = (node: ts.Node): ts.VisitResult<ts.Node> => {
          if (ts.isJsxText(node)) {
            const trimmed = node.text.trim()
            // JSX text is often wrapped across lines for readability.
            // Compare catalog keys against a normalized display string.
            const key = keys.has(trimmed) ? trimmed : trimmed.replace(/\\s+/g, ' ')
            if (!keys.has(key)) return node
            replaced++
            const leading = node.text.match(/^\s*/)?.[0] || ''
            const trailing = node.text.match(/\s*$/)?.[0] || ''
            return ts.factory.createJsxFragment(
              ts.factory.createJsxOpeningFragment(),
              [
                ...(leading ? [ts.factory.createJsxText(leading)] : []),
                ts.factory.createJsxExpression(undefined, makeCall(key)),
                ...(trailing ? [ts.factory.createJsxText(trailing)] : []),
              ],
              ts.factory.createJsxJsxClosingFragment(),
            )
          }
          if (ts.isJsxAttribute(node) && presentationAttributes.has(node.name.getText(source))) {
            const initializer = node.initializer
            if (initializer && ts.isStringLiteral(initializer) && keys.has(initializer.text)) {
              replaced++
              return ts.factory.updateJsxAttribute(
                node, node.name, ts.factory.createJsxExpression(undefined, makeCall(initializer.text)),
              )
            }
            if (initializer && ts.isJsxExpression(initializer) && initializer.expression) {
              const old = initializer.expression
              const converted = presentation(old)
              if (converted !== old) {
                replaced++
                return ts.factory.updateJsxAttribute(
                  node, node.name, ts.factory.updateJsxExpression(initializer, converted),
                )
              }
            }
          }
          if (ts.isJsxExpression(node) && node.expression && ts.isStringLiteral(node.expression)) {
            const converted = presentation(node.expression)
            if (converted !== node.expression) {
              replaced++
              return ts.factory.updateJsxExpression(node, converted)
            }
          }
          return ts.visitEachChild(node, visit, context)
        }
        return ts.visitNode(root, visit) as ts.SourceFile
      }
      const transformed = ts.transform(source, [transformer])
      try {
        if (!replaced) return null
        return {
          code: "import { tx as __tx } from './i18n'\n" +
            ts.createPrinter({ newLine: ts.NewLineKind.LineFeed }).printFile(transformed.transformed[0]),
          map: null,
        }
      } finally { transformed.dispose() }
    },
  }
}
