import type { ActivityEvent } from "../lib/types";

export function ActivityLog({
  events,
  title = "What happened",
  caption = "Shared desk",
  onReplay,
}: {
  events: ActivityEvent[];
  title?: string;
  caption?: string;
  onReplay?: (event: ActivityEvent) => void;
}) {
  return (
    <section className="panel log">
      <div className="heading">
        <div>
          <small>{caption}</small>
          <h2>{title}</h2>
        </div>
        <b>{events.length}</b>
      </div>
      <ol>
        {events.length ? (
          events.map((event) => (
            <li key={event.event_id} data-actor={event.actor}>
              <span>{event.actor_type ?? event.actor}</span>
              <strong>{event.message}</strong>
              <small>
                {event.tool ?? "ui"} · {event.invocation_channel ?? "backend"} · {event.authorization_source ?? "—"} ·{" "}
                {new Date(event.at).toLocaleTimeString()}
              </small>
              {onReplay && event.viewer_document_id && event.viewer_page ? (
                <button type="button" onClick={() => onReplay(event)}>
                  Replay page {event.viewer_page}
                </button>
              ) : null}
            </li>
          ))
        ) : (
          <li className="empty">No human or agent actions yet.</li>
        )}
      </ol>
    </section>
  );
}
