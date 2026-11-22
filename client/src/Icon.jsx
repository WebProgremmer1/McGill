const paths = {
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></>,
  walk: <><circle cx="14" cy="4" r="2" /><path d="m7 21 3-7 3 3v4M6 11l4-4 4 1 3 5h3M10 7l-1 7 6 2" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  phone: <path d="M7 3H3v3c0 8 7 15 15 15h3v-4l-5-2-2 2a15 15 0 0 1-7-7l2-2-2-5Z" />,
  pin: <><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z" /><circle cx="12" cy="10" r="2.5" /></>,
  heart: <path d="M12 21 3 12C-3 4 7-2 12 5c5-7 15-1 9 7Z" />,
  cup: <><path d="M4 8h13v7a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5ZM17 9h2a3 3 0 0 1 0 6h-2M7 2v3m5-3v3" /></>,
  calendar: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M16 3v4M8 3v4M3 10h18" /></>,
  signIn: <path d="M14 4h5a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-5M4 12h11m-4-4 4 4-4 4" />,
  signOut: <path d="M10 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h5m0-8h10m-4-4 4 4-4 4" />,
  back: <path d="M20 12H4m6-6-6 6 6 6" />,
  next: <path d="M4 12h16m-6-6 6 6-6 6" />,
  users: <><circle cx="9" cy="8" r="3.5" /><path d="M3 20c0-4 2.5-6 6-6s6 2 6 6M16 5a3.5 3.5 0 0 1 0 6.5M18 14.5c2 .8 3 2.6 3 5.5" /></>,
  person: <><circle cx="12" cy="8" r="4" /><path d="M4.5 21c0-4.5 3.2-7 7.5-7s7.5 2.5 7.5 7" /></>,
  message: <path d="M4 5h16a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H10l-5 4v-4H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1ZM7.5 9.5h9m-9 3.5h6" />,
  retry: <path d="M20 11a8 8 0 1 0-2.3 6.7M20 5v6h-6" />,
  home: <path d="M3 11.5 12 4l9 7.5M5.5 10v10h13V10M10 20v-6h4v6" />,
  help: <><circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.5 2.5 0 1 1 3.6 2.2c-.8.4-1.1 1-1.1 1.8M12 17h.01" /></>,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  stop: <><circle cx="12" cy="12" r="9" /><path d="m9 9 6 6m0-6-6 6" /></>,
}

export default function Icon({ name, ...props }) {
  return <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name]}</svg>
}
