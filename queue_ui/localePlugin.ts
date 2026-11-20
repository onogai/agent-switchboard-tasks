import uk from './src/locales/uk.json'
import es from './src/locales/es-ES.json'
import ts from 'typescript'
import type { Plugin } from 'vite'

/**
 * Build-time JSX localization. The dictionaries are data-only, and only
 * explicitly catalogued presentation strings are transformed. Identifiers,
 * API payloads, user content and non-JSX JavaScript are never localized.
 */
export function localePlugin(): Plugin {
  const keys = new Set([...Object.keys(uk), ...Object.keys(es)])
  const noTranslateAttribute = new Set([
    'id', 'key', 'name', 'value', 'to', 'href', 'src', 'type', 'variant',
    'color', 'size', 'target', 'rel', 'role', 'component', 'method', 'action',
    'inputMode', 'autoComplete', 'fontFamily', 'justifyContent', 'alignItems',
  ])

  const makeCall = (value: string): ts.CallExpression =>
    ts.factory.createCallExpression(ts.factory.createIdentifier('__tx'), undefined,
      [ts.factory.createStringLiteral(value)])

  return {
    name: 'switchboard-locale-catalogs',
    enforce: 'pre',
    transform(code, id) {
      const file = id.split('?')[0]
      if (!file.endsWith('.tsx') || !file.includes('/src/')) return null
      const source = ts.createSourceFile(file, code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
      let replaced = 0
      const transformer: ts.TransformerFactory<ts.SourceFile> = context => rootNode => {
        const visit = (node: ts.Node, inJsx: boolean, parent?: ts.Node): ts.VisitResult<ts.Node> => {
          if (ts.isJsxText(node)) {
            const trimmed = node.text.trim()
            if (!keys.has(trimmed)) return node
            replaced++
            const leading = node.text.match(/^\s*/)?.[0] || ''
            const trailing = node.text.match(/\s*$/)?.[0] || ''
            return ts.factory.createJsxFragment(
              ts.factory.createJsxOpeningFragment(),
              [
                ...(leading ? [ts.factory.createJsxText(leading)] : []),
                ts.factory.createJsxExpression(undefined, makeCall(trimmed)),
                ...(trailing ? [ts.factory.createJsxText(trailing)] : []),
              ],
              ts.factory.createJsxJsxClosingFragment(),
            )
          }
          if (ts.isJsxAttribute(node)) {
            const attr = node.name.getText(source)
            if (node.initializer && ts.isStringLiteral(node.initializer) &&
                !noTranslateAttribute.has(attr) && keys.has(node.initializer.text)) {
              replaced++
              return ts.factory.updateJsxAttribute(node, node.name,
                ts.factory.createJsxExpression(undefined, makeCall(node.initializer.text)))
            }
          }
          if (inJsx && ts.isStringLiteral(node) && keys.has(node.text) &&
              !(parent && ts.isJsxAttribute(parent)) &&
              !(parent && ts.isBinaryExpression(parent)) &&
              !(parent && ts.isPropertyAssignment(parent) && parent.name === node)) {
            replaced++
            return makeCall(node.text)
          }
          const isJsx = inJsx || ts.isJsxElement(node) || ts.isJsxFragment(node) ||
            ts.isJsxSelfClosingElement(node)
          return ts.visitEachChild(node, child => visit(child, isJsx, node), context)
        }
        return ts.visitNode(rootNode, node => visit(node, false)) as ts.SourceFile
      }
      const transformed = ts.transform(source, [transformer])
      try {
        if (!replaced) return null
        const printed = ts.createPrinter({ newLine: ts.NewLineKind.LineFeed })
          .printFile(transformed.transformed[0])
        return { code: "import { tx as __tx } from './i18n'\n" + printed, map: null }
      } finally {
        transformed.dispose()
      }
    },
  }
}
