import { useCallback, useEffect, useRef, useState } from 'react'
import { liveMapUrl, readMapsConfig, viewerUrl } from './data/journeyApi.js'
import Icon from './Icon.jsx'

// Backup map: runs inside the backend's Leaflet viewer. Labels come from the API journey
// because that viewer's own route drawing hardcodes Home and Tim Hortons.
const drawInViewer = `(text) => {
  const journey = JSON.parse(text);
  reset();
  (journey.safe_zones || []).forEach(z => layers.push(L.circle([z.latitude, z.longitude], { radius: z.radius_m, color: "#6B7F6A", weight: 2, fillColor: "#6B7F6A", fillOpacity: 0.1, dashArray: "4 8", lineCap: "round" }).addTo(map)));
  const points = journey.route.map(p => [p.latitude, p.longitude]);
  const start = [journey.start.latitude, journey.start.longitude];
  const end = [journey.destination.latitude, journey.destination.longitude];
  layers.push(L.polyline(points, { color: "#FFF6E8", weight: 11, opacity: 0.9, lineCap: "round", lineJoin: "round" }).addTo(map));
  layers.push(L.polyline(points, { color: "#6E5683", weight: 5, opacity: 0.9, lineCap: "round", lineJoin: "round" }).addTo(map));
  layers.push(L.circleMarker(start, { radius: 9, color: "#FFF6E8", weight: 3, fillColor: "#6E5683", fillOpacity: 1 }).addTo(map).bindTooltip(journey.start.name, { permanent: true, direction: "top" }));
  layers.push(L.circleMarker(end, { radius: 11, color: "#FFF6E8", weight: 3, fillColor: "#A8435A", fillOpacity: 1 }).addTo(map).bindTooltip(journey.destination.name, { permanent: true, direction: "top", offset: [0, -10] }));
  document.getElementById("map").classList.toggle("wn-movable", Boolean(journey.movable));
  if (journey.latest) {
    const point = [journey.latest.latitude, journey.latest.longitude];
    const halo = L.circleMarker(point, { radius: 16, stroke: false, fillColor: "#F0B04F", fillOpacity: 0.35, interactive: false }).addTo(map);
    // In the demo the dot can be dragged; dropping it sends the new spot to the dashboard.
    const me = L.marker(point, { draggable: Boolean(journey.movable), keyboard: false, zIndexOffset: 1000,
      icon: L.divIcon({ className: "wn-me", iconSize: [22, 22] }) }).addTo(map)
      .bindTooltip(journey.movable ? "Last known location · drag to move" : "Last known location");
    me.on("drag", e => halo.setLatLng(e.target.getLatLng()));
    me.on("dragend", e => { const p = e.target.getLatLng(); window.whatsNextMove && window.whatsNextMove(p.lat, p.lng); });
    layers.push(halo, me);
    points.push(point);
  }
  map.invalidateSize();
  map.fitBounds(L.latLngBounds(points.concat([start, end])).pad(0.35));
}`

function BackupJourneyMap({ journey, onMove }) {
  const frame = useRef(null)
  const draw = useRef(null)
  const [status, setStatus] = useState('loading')
  const view = JSON.stringify({
    route: journey.route,
    safe_zones: journey.safe_zones,
    start: journey.start,
    destination: journey.destination,
    latest: journey.latest_location,
    movable: Boolean(onMove),
  })
  const moveRef = useRef(onMove)
  useEffect(() => { moveRef.current = onMove }, [onMove])

  useEffect(() => {
    if (status !== 'loading') return undefined
    const timer = setTimeout(() => setStatus('unavailable'), 15000)
    return () => clearTimeout(timer)
  }, [status])

  useEffect(() => {
    if (status !== 'ready') return
    try {
      draw.current(view)
    } catch {
      setStatus('unavailable')
    }
  }, [status, view])

  function handleLoad() {
    try {
      const viewer = frame.current.contentWindow
      if (!viewer.L || !viewer.reset) throw new Error('Viewer did not load.')
      const style = viewer.document.createElement('style')
      // The panel's controls create journeys and alerts, so dashboards show only the map.
      style.textContent = '#panel { display: none !important; } body { height: 100vh; }'
        + ' .wn-me { box-sizing: border-box; border-radius: 50%; background: #3B2B45; border: 3px solid #FFF6E8; box-shadow: 0 2px 6px rgba(59,43,69,.45); }'
        + ' .wn-movable.leaflet-container { cursor: crosshair; } .wn-movable .wn-me { cursor: grab; } .wn-movable .wn-me:active { cursor: grabbing; }'
      viewer.document.head.append(style)
      // Clicking anywhere on the map also moves the walker there (only when the dashboard allows it).
      viewer.whatsNextMove = (latitude, longitude) => moveRef.current?.(latitude, longitude)
      viewer.eval('map').on('click', event => viewer.whatsNextMove(event.latlng.lat, event.latlng.lng))
      draw.current = viewer.eval(drawInViewer)
      setStatus('ready')
    } catch {
      setStatus('unavailable')
    }
  }

  return (
    <>
      <iframe ref={frame} src={viewerUrl} title={`Map of the walk to ${journey.destination.name}`}
        className={status === 'ready' ? undefined : 'map-pending'} onLoad={handleLoad} />
      {status !== 'ready' && <p className="map-status">{status === 'loading' ? 'Loading map…' : 'Map unavailable.'}</p>}
    </>
  )
}

function GoogleJourneyMap({ journey, onFailed, wayfinding, onMove }) {
  const frame = useRef(null)
  const [ready, setReady] = useState(false)
  const payload = JSON.stringify({
    id: journey.id,
    route: journey.route,
    route_source: journey.route_source,
    route_warning: journey.route_warning,
    route_distance_m: journey.route_distance_m,
    route_duration_s: journey.route_duration_s,
    safe_zones: journey.safe_zones,
    start: journey.start,
    destination: journey.destination,
    track: journey.track,
    // The Patient map stays neutral, so risk never changes its colors.
    risk: { level: wayfinding ? 'low' : journey.risk.level },
  })
  const movable = Boolean(onMove)
  const moveRef = useRef(onMove)
  useEffect(() => { moveRef.current = onMove }, [onMove])

  useEffect(() => {
    function receive(event) {
      if (event.origin !== window.location.origin || event.source !== frame.current?.contentWindow) return
      if (event.data?.type !== 'whats-next-map' || event.data.journey !== journey.id) return
      if (event.data.status === 'ready') {
        // The viewer's off-route distance bands are monitoring detail, not wayfinding.
        if (wayfinding) frame.current.contentWindow.eval('mk.bands.forEach(band => band.line.setMap(null))')
        setReady(true)
      }
      if (event.data.status === 'failed') onFailed()
      if (event.data.status === 'move' && Number.isFinite(event.data.latitude) && Number.isFinite(event.data.longitude)) {
        moveRef.current?.(event.data.latitude, event.data.longitude)
      }
    }
    window.addEventListener('message', receive)
    return () => window.removeEventListener('message', receive)
  }, [journey.id, onFailed, wayfinding])

  useEffect(() => {
    if (ready) return undefined
    const timer = setTimeout(onFailed, 15000)
    return () => clearTimeout(timer)
  }, [onFailed, ready])

  // The dashboard passes only the journey it was already authorized to read.
  useEffect(() => {
    if (!ready) return
    frame.current?.contentWindow?.postMessage({ type: 'whats-next-journey', journey: JSON.parse(payload), movable }, window.location.origin)
  }, [movable, payload, ready])

  return (
    <>
      <iframe ref={frame} src={`/viewer/live-map.html?embed=1&journey=${encodeURIComponent(journey.id)}`}
        title={`Google map of the walk to ${journey.destination.name}`} className={ready ? undefined : 'map-pending'} />
      {!ready && <p className="map-status">Loading map…</p>}
    </>
  )
}

export default function JourneyMap({ journey, presenter = false, wayfinding = false, onMove = null }) {
  const [provider, setProvider] = useState('checking')
  const [googleFailed, setGoogleFailed] = useState(false)

  useEffect(() => {
    let active = true
    readMapsConfig().then(config => {
      if (active) setProvider(config.maps_enabled ? 'google' : 'backup')
    })
    return () => { active = false }
  }, [])

  const useBackup = useCallback(() => {
    setGoogleFailed(true)
    setProvider('backup')
  }, [])

  return (
    <>
      <div className="journey-map" data-journey-id={journey.id} data-map-provider={provider} data-route-source={journey.route_source}>
        {provider === 'checking' && <p className="map-status">Loading map…</p>}
        {provider === 'google' && <GoogleJourneyMap key={journey.id} journey={journey} onFailed={useBackup} wayfinding={wayfinding} onMove={onMove} />}
        {provider === 'backup' && <BackupJourneyMap journey={journey} onMove={onMove} />}
        {googleFailed && <p className="map-note" role="status">Google map unavailable. Showing the backup map.</p>}
      </div>
      {onMove && provider !== 'checking' && (
        <p className="map-hint"><Icon name="pin" />Tap the map, or drag the dark dot, to move the location.</p>
      )}
      {presenter && provider === 'google' && (
        <p className="map-presenter">
          <a className="directions-link" href={liveMapUrl(journey.id)}
            target="_blank" rel="noopener">Open full viewer (new tab)</a>
        </p>
      )}
    </>
  )
}
