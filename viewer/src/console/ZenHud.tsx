// ZenHud: High-immersion flight cockpit HUD for full-screen 3D graph exploration.
// Enables seamless navigation using mouse D-pad, camera presets, node cycling,
// zoom/elevation, and quick cheatsheet drawer.

import { useState } from 'react'
import type { CNode } from './model'
import type { CameraPreset } from './zenControls'
import { IconFit } from './icons'

interface ZenHudProps {
  selectedNode: CNode | null
  totalNodes: number
  isInsideRoom: boolean
  onOrbit: (dTheta: number, dPhi: number) => void
  onPan: (dx: number, dy: number) => void
  onElevate: (dy: number) => void
  onZoom: (k: number) => void
  onPreset: (preset: CameraPreset) => void
  onCycleNode: (direction: 1 | -1) => void
  onFit: () => void
  onEnterRoom: () => void
  onExitRoom: () => void
  onExitZen: () => void
}

export function ZenHud({
  selectedNode,
  totalNodes,
  isInsideRoom,
  onOrbit,
  onPan,
  onElevate,
  onZoom,
  onPreset,
  onCycleNode,
  onFit,
  onEnterRoom,
  onExitRoom,
  onExitZen,
}: ZenHudProps) {
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const [panMode, setPanMode] = useState(false)
  const [collapsed, setCollapsed] = useState(false)

  const step = 0.14
  const handleDirection = (dx: number, dy: number) => {
    if (panMode) {
      onPan(dx, dy)
    } else {
      onOrbit(dx * step, -dy * step)
    }
  }

  return (
    <>
      {/* Top Telemetry & Control Strip */}
      <div className="xc-zen-topbar" role="toolbar" aria-label="Zen Flight Navigation">
        <div className="xc-zen-brand">
          <span className="xc-zen-icon" aria-hidden="true">🌌</span>
          <span className="xc-zen-title">ZEN IMMERSION</span>
          <span className="xc-zen-mode-badge">
            {isInsideRoom ? 'INNER SANCTUM ROOM' : 'GLOBAL ORBIT'}
          </span>
        </div>

        {/* Node Carousel Navigator */}
        <div className="xc-zen-node-strip">
          <button
            type="button"
            className="xc-zen-btn"
            onClick={() => onCycleNode(-1)}
            title="Previous node (Shift+Tab)"
            aria-label="Previous node"
          >
            ◀
          </button>
          <div className="xc-zen-node-label" title={selectedNode ? selectedNode.label : 'No node selected (Press Tab)'}>
            {selectedNode ? (
              <>
                <span className="xc-zen-cls-tag">[{selectedNode.cls.toUpperCase()}]</span>
                <span className="xc-zen-name">{selectedNode.label}</span>
                <span className="xc-zen-deg">deg: {selectedNode.degree}</span>
              </>
            ) : (
              <span className="xc-zen-placeholder">Select node or press Tab to cycle ({totalNodes} nodes)</span>
            )}
          </div>
          <button
            type="button"
            className="xc-zen-btn"
            onClick={() => onCycleNode(1)}
            title="Next node (Tab)"
            aria-label="Next node"
          >
            ▶
          </button>
        </div>

        {/* Actions - Icon Only */}
        <div className="xc-zen-actions">
          {isInsideRoom ? (
            <button
              type="button"
              className="xc-zen-action-btn xc-zen-action-btn--ascend"
              onClick={onExitRoom}
              title="Ascend back to global graph orbit (ESC)"
              aria-label="Ascend to global orbit"
            >
              🚀
            </button>
          ) : (
            selectedNode && (
              <button
                type="button"
                className="xc-zen-action-btn xc-zen-action-btn--dive"
                onClick={onEnterRoom}
                title="Enter Inner World Sanctum Room (Enter)"
                aria-label="Enter Inner Sanctum Room"
              >
                🪐
              </button>
            )
          )}

          <button
            type="button"
            className="xc-zen-btn"
            onClick={() => setShortcutsOpen((v) => !v)}
            title="Toggle keyboard navigation cheatsheet"
            aria-label="Toggle keyboard shortcuts"
            aria-expanded={shortcutsOpen}
          >
            ⌨️
          </button>

          <button
            type="button"
            className="xc-zen-btn xc-zen-btn--exit"
            onClick={onExitZen}
            title="Exit Zen mode (Z or ESC)"
            aria-label="Exit Zen mode"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Bottom Right Floating Flight Cockpit (D-Pad & Presets) */}
      {collapsed ? (
        <div
          className="xc-zen-flight-cockpit xc-zen-flight-cockpit--collapsed"
          role="region"
          aria-label="Camera Flight Controls"
        >
          <button
            type="button"
            className="xc-zen-expand-btn"
            onClick={() => setCollapsed(false)}
            title="Expand flight navigation controls (D-Pad)"
            aria-label="Expand flight controls"
          >
            🧭
          </button>
        </div>
      ) : (
        <div
          className="xc-zen-flight-cockpit"
          role="region"
          aria-label="Camera Flight Controls"
        >
          <div
            className="xc-zen-cockpit-header"
            onClick={() => setCollapsed(true)}
            title="Click header to collapse flight controls card"
          >
            <span className="xc-zen-cockpit-title">FLIGHT D-PAD</span>
            <div className="xc-zen-cockpit-actions" onClick={(e) => e.stopPropagation()}>
              <button
                type="button"
                className="xc-zen-toggle-pill"
                onClick={() => setPanMode((v) => !v)}
                data-mode={panMode ? 'pan' : 'orbit'}
                title={panMode ? 'Mode: Pan (Click for Orbit)' : 'Mode: Orbit (Click for Pan)'}
                aria-label={panMode ? 'Mode: Pan' : 'Mode: Orbit'}
              >
                {panMode ? '✋' : '🔄'}
              </button>
              <button
                type="button"
                className="xc-zen-mini-btn"
                onClick={() => setCollapsed(true)}
                title="Collapse flight controls card"
                aria-label="Collapse flight controls"
              >
                ▼
              </button>
            </div>
          </div>

          <div className="xc-zen-cockpit-grid">
            {/* Compass D-Pad */}
            <div className="xc-zen-dpad" role="group" aria-label="Directional Navigation">
              <button
                type="button"
                className="xc-zen-dpad-btn xc-zen-dpad-up"
                onClick={() => handleDirection(0, 1)}
                title={panMode ? 'Pan Up' : 'Orbit Pitch Down (Up Arrow / W)'}
                aria-label="Up"
              >
                ▲
              </button>
              <div className="xc-zen-dpad-row">
                <button
                  type="button"
                  className="xc-zen-dpad-btn xc-zen-dpad-left"
                  onClick={() => handleDirection(-1, 0)}
                  title={panMode ? 'Pan Left' : 'Orbit Yaw Left (Left Arrow / A)'}
                  aria-label="Left"
                >
                  ◀
                </button>
                <button
                  type="button"
                  className="xc-zen-dpad-btn xc-zen-dpad-center"
                  onClick={onFit}
                  title="Frame entire graph (Space / F)"
                  aria-label="Fit Graph"
                >
                  <IconFit style={{ width: 11, height: 11 }} />
                </button>
                <button
                  type="button"
                  className="xc-zen-dpad-btn xc-zen-dpad-right"
                  onClick={() => handleDirection(1, 0)}
                  title={panMode ? 'Pan Right' : 'Orbit Yaw Right (Right Arrow / D)'}
                  aria-label="Right"
                >
                  ▶
                </button>
              </div>
              <button
                type="button"
                className="xc-zen-dpad-btn xc-zen-dpad-down"
                onClick={() => handleDirection(0, -1)}
                title={panMode ? 'Pan Down' : 'Orbit Pitch Up (Down Arrow / S)'}
                aria-label="Down"
              >
                ▼
              </button>
            </div>

            {/* Elevation & Zoom 2x2 Grid - Icon Only */}
            <div className="xc-zen-axis-controls">
              <div className="xc-zen-axis-row">
                <button
                  type="button"
                  className="xc-zen-axis-btn"
                  onClick={() => onZoom(1.3)}
                  title="Zoom in (+ or =)"
                  aria-label="Zoom in"
                >
                  +
                </button>
                <button
                  type="button"
                  className="xc-zen-axis-btn"
                  onClick={() => onElevate(1)}
                  title="Elevate camera up (Q)"
                  aria-label="Elevate up"
                >
                  ⇡
                </button>
              </div>
              <div className="xc-zen-axis-row">
                <button
                  type="button"
                  className="xc-zen-axis-btn"
                  onClick={() => onZoom(1 / 1.3)}
                  title="Zoom out (- or _)"
                  aria-label="Zoom out"
                >
                  −
                </button>
                <button
                  type="button"
                  className="xc-zen-axis-btn"
                  onClick={() => onElevate(-1)}
                  title="Lower camera down (E)"
                  aria-label="Lower down"
                >
                  ⇣
                </button>
              </div>
            </div>
          </div>

          {/* Camera Angle Presets - Icon Only */}
          <div className="xc-zen-presets" role="group" aria-label="Camera Presets">
            <button
              type="button"
              className="xc-zen-preset-btn"
              data-preset="iso"
              onClick={() => onPreset('iso')}
              title="1 · Isometric 3D view (Key 1)"
              aria-label="Isometric view (1)"
            >
              ⬡
            </button>
            <button
              type="button"
              className="xc-zen-preset-btn"
              data-preset="top"
              onClick={() => onPreset('top')}
              title="2 · Top-down plan view (Key 2)"
              aria-label="Top-down view (2)"
            >
              ⊞
            </button>
            <button
              type="button"
              className="xc-zen-preset-btn"
              data-preset="front"
              onClick={() => onPreset('front')}
              title="3 · Front elevation view (Key 3)"
              aria-label="Front view (3)"
            >
              ▣
            </button>
            <button
              type="button"
              className="xc-zen-preset-btn"
              data-preset="side"
              onClick={() => onPreset('side')}
              title="4 · Side profile view (Key 4)"
              aria-label="Side view (4)"
            >
              ◧
            </button>
          </div>
        </div>
      )}

      {/* Floating Keyboard Shortcuts Cheatsheet Drawer */}
      {shortcutsOpen && (
        <div className="xc-zen-shortcuts-modal" role="dialog" aria-modal="true" aria-label="Keyboard Shortcuts Cheatsheet">
          <div className="xc-zen-shortcuts-header">
            <span style={{ fontWeight: 700, letterSpacing: '0.06em', color: 'var(--accent)' }}>
              ZEN KEYBOARD NAVIGATION CHEATSHEET
            </span>
            <button
              type="button"
              className="xc-zen-btn"
              onClick={() => setShortcutsOpen(false)}
              aria-label="Close shortcuts cheatsheet"
            >
              ✕
            </button>
          </div>
          <div className="xc-zen-shortcuts-body">
            <div className="xc-zen-shortcut-row">
              <span className="xc-zen-key">Arrows / WASD</span>
              <span className="xc-zen-desc">Smooth 3D camera orbit & dolly</span>
            </div>
            <div className="xc-zen-shortcut-row">
              <span className="xc-zen-key">Shift + Arrows / WASD</span>
              <span className="xc-zen-desc">Pan camera laterally in camera plane</span>
            </div>
            <div className="xc-zen-shortcut-row">
              <span className="xc-zen-key">Q / E</span>
              <span className="xc-zen-desc">Elevate camera altitude up / down</span>
            </div>
            <div className="xc-zen-shortcut-row">
              <span className="xc-zen-key">+ / − or [ / ]</span>
              <span className="xc-zen-desc">Zoom camera in / out</span>
            </div>
            <div className="xc-zen-shortcut-row">
              <span className="xc-zen-key">Tab / Shift+Tab</span>
              <span className="xc-zen-desc">Cycle next / previous node with auto-frame</span>
            </div>
            <div className="xc-zen-shortcut-row">
              <span className="xc-zen-key">1 / 2 / 3 / 4</span>
              <span className="xc-zen-desc">Camera Presets: Isometric, Top, Front, Side</span>
            </div>
            <div className="xc-zen-shortcut-row">
              <span className="xc-zen-key">Enter</span>
              <span className="xc-zen-desc">Zoom inside node into Inner Sanctum Room</span>
            </div>
            <div className="xc-zen-shortcut-row">
              <span className="xc-zen-key">Escape</span>
              <span className="xc-zen-desc">Ascend from room to orbit / Clear selection</span>
            </div>
            <div className="xc-zen-shortcut-row">
              <span className="xc-zen-key">Space / F / 0</span>
              <span className="xc-zen-desc">Fit / Frame entire graph cloud</span>
            </div>
            <div className="xc-zen-shortcut-row">
              <span className="xc-zen-key">Z</span>
              <span className="xc-zen-desc">Toggle Zen Immersion Mode</span>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
