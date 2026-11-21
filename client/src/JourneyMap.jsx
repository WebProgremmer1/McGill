import { useEffect, useRef, useState } from 'react'
import { viewerUrl } from './data/journeyApi.js'

// Runs inside the backend viewer's Leaflet map. Labels come from the API journey
// because the viewer's own route drawing hardcodes Home and Tim Hortons.
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

export default function JourneyMap({ journey }) {
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
      // The panel's controls create journeys and alerts, so Today shows only the map.
      style.textContent = '#panel { display: none !important; } body { height: 100vh; }'
      viewer.document.head.append(style)
      draw.current = viewer.eval(drawInViewer)
      setStatus('ready')
    } catch {
      setStatus('unavailable')
    }
  }

  return (
    <div className="journey-map">
      <iframe ref={frame} src={viewerUrl} title={`Map of the walk to ${journey.destination.name}`}
        className={status === 'ready' ? undefined : 'map-pending'} onLoad={handleLoad} />
      {status !== 'ready' && <p className="map-status">{status === 'loading' ? 'Loading map…' : 'Map unavailable.'}</p>}
    </div>
  )
}
