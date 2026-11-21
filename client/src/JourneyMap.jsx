import { useCallback, useEffect, useRef, useState } from 'react'
import { readMapsConfig, viewerUrl } from './data/journeyApi.js'

// Backup map: runs inside the backend's Leaflet viewer. Labels come from the API journey
// because that viewer's own route drawing hardcodes Home and Tim Hortons.
const drawInViewer = `(text) => {
  const journey = JSON.parse(text);
  reset();
  (journey.safe_zones || []).forEach(z => layers.push(L.circle([z.latitude, z.longitude], { radius: z.radius_m, color: "#2e9e4f", weight: 2, fillColor: "#2e9e4f", fillOpacity: 0.07, dashArray: "6" }).addTo(map)));
  const points = journey.route.map(p => [p.latitude, p.longitude]);
  const start = [journey.start.latitude, journey.start.longitude];
  const end = [journey.destination.latitude, journey.destination.longitude];
  layers.push(L.polyline(points, { color: "#1a73e8", weight: 5, opacity: 0.7 }).addTo(map));
  layers.push(L.circleMarker(start, { radius: 9, color: "#fff", weight: 3, fillColor: "#1a73e8", fillOpacity: 1 }).addTo(map).bindTooltip(journey.start.name, { permanent: true, direction: "top" }));
  layers.push(L.marker(end, { keyboard: false }).addTo(map).bindTooltip(journey.destination.name, { permanent: true, direction: "top", offset: [-15, -28] }));
  if (journey.latest) {
    const point = [journey.latest.latitude, journey.latest.longitude];
    layers.push(L.circleMarker(point, { radius: 9, color: "#000", weight: 2, fillColor: "#8a2f1d", fillOpacity: 1 }).addTo(map).bindTooltip("Last known location"));
    points.push(point);
  }
  map.invalidateSize();
  map.fitBounds(L.latLngBounds(points.concat([start, end])).pad(0.35));
}`

function BackupJourneyMap({ journey }) {
  const frame = useRef(null)
  const draw = useRef(null)
  const [status, setStatus] = useState('loading')
  const view = JSON.stringify({
    route: journey.route,
    safe_zones: journey.safe_zones,
    start: journey.start,
    destination: journey.destination,
    latest: journey.latest_location,
  })

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
      viewer.document.head.append(style)
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

function GoogleJourneyMap({ journey, onFailed }) {
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
    risk: { level: journey.risk.level },
  })

  useEffect(() => {
    function receive(event) {
      if (event.origin !== window.location.origin || event.source !== frame.current?.contentWindow) return
      if (event.data?.type !== 'whats-next-map' || event.data.journey !== journey.id) return
      if (event.data.status === 'ready') setReady(true)
      if (event.data.status === 'failed') onFailed()
    }
    window.addEventListener('message', receive)
    return () => window.removeEventListener('message', receive)
  }, [journey.id, onFailed])

  useEffect(() => {
    if (ready) return undefined
    const timer = setTimeout(onFailed, 15000)
    return () => clearTimeout(timer)
  }, [onFailed, ready])

  // The dashboard passes only the journey it was already authorized to read.
  useEffect(() => {
    if (!ready) return
    frame.current?.contentWindow?.postMessage({ type: 'whats-next-journey', journey: JSON.parse(payload) }, window.location.origin)
  }, [payload, ready])

  return (
    <>
      <iframe ref={frame} src={`/viewer/live-map.html?embed=1&journey=${encodeURIComponent(journey.id)}`}
        title={`Google map of the walk to ${journey.destination.name}`} className={ready ? undefined : 'map-pending'} />
      {!ready && <p className="map-status">Loading map…</p>}
    </>
  )
}

export default function JourneyMap({ journey }) {
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
    <div className="journey-map" data-journey-id={journey.id} data-map-provider={provider} data-route-source={journey.route_source}>
      {provider === 'checking' && <p className="map-status">Loading map…</p>}
      {provider === 'google' && <GoogleJourneyMap key={journey.id} journey={journey} onFailed={useBackup} />}
      {provider === 'backup' && <BackupJourneyMap journey={journey} />}
      {googleFailed && <p className="map-note" role="status">Google map unavailable. Showing the backup map.</p>}
    </div>
  )
}
