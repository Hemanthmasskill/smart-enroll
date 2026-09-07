import "./NotificationItem.css";

export default function NotificationItem({ notification, onMarkRead }) {
  const { title, description, timestamp, read } = notification;

  return (
    <li className={`notification-item ${read ? "" : "unread"}`}>
      <span className="notification-dot" aria-hidden="true" />
      <div className="notification-body">
        <div className="notification-top">
          <h3 className="notification-title">{title}</h3>
          {!read && <span className="notification-badge">New</span>}
        </div>
        <p className="notification-description">{description}</p>
        <div className="notification-bottom">
          <span className="notification-timestamp">{timestamp}</span>
          {!read && (
            <button className="notification-mark-read" onClick={onMarkRead}>
              Mark as Read
            </button>
          )}
        </div>
      </div>
    </li>
  );
}
