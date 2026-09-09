import { useEffect, useId, useState } from 'react'

let mermaidReady: Promise<typeof import('mermaid').default> | null = null

function loadMermaid() {
  if (!mermaidReady) {
    mermaidReady = import('mermaid').then(({ default: mermaid }) => {
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: 'base',
        themeVariables: {
          background: '#090b15',
          primaryColor: '#171b36',
          primaryTextColor: '#eef0ff',
          primaryBorderColor: '#858cf4',
          lineColor: '#6971ba',
          secondaryColor: '#101426',
          tertiaryColor: '#0b0e19',
          fontFamily: 'Manrope, Inter, system-ui, sans-serif',
          fontSize: '13px',
        },
        flowchart: { curve: 'basis', htmlLabels: true },
      })
      return mermaid
    })
  }
  return mermaidReady
}

export function MermaidDiagram({ chart, label }: { chart: string; label: string }) {
  const reactId = useId()
  const [svg, setSvg] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const diagramId = `cortex-mermaid-${reactId.replace(/[^a-zA-Z0-9_-]/g, '')}`
    loadMermaid()
      .then((mermaid) => mermaid.render(diagramId, chart))
      .then(({ svg: rendered }) => {
        if (active) setSvg(rendered)
      })
      .catch(() => {
        if (active) setError('Diagram could not be rendered.')
      })
    return () => { active = false }
  }, [chart, reactId])

  return (
    <figure className="cortex-mermaid" aria-label={label}>
      {svg ? <div className="cortex-mermaid-svg" dangerouslySetInnerHTML={{ __html: svg }} /> : <div className="cortex-mermaid-loading">{error || 'Rendering architecture…'}</div>}
    </figure>
  )
}
