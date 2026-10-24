"""목록과 미리보기에서 공통으로 사용하는 작은 색상 태그 표시예요."""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from tagger.colors import DEFAULT_TAG_COLOR, badge_palette

BADGES_ROLE = Qt.UserRole + 1
COUNT_ROLE = Qt.UserRole + 2


def paint_badge(painter, rect, text, color):
    background, foreground = badge_palette(color)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(background))
    painter.drawRoundedRect(rect, 4, 4)
    painter.setPen(QColor(foreground))
    painter.drawText(rect.adjusted(7, 0, -7, 0), Qt.AlignVCenter | Qt.AlignLeft, text)


class TagBadgeDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        badges = index.data(BADGES_ROLE)
        if not badges:
            return super().paint(painter, option, index)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        painter.save()
        painter.setClipRect(opt.rect)
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(opt.font)
        area = style.subElementRect(QStyle.SE_ItemViewItemText, opt, opt.widget).adjusted(4, 0, -4, 0)
        metrics = opt.fontMetrics
        count = index.data(COUNT_ROLE)
        if count is not None:
            count_text = str(count)
            count_width = metrics.horizontalAdvance(count_text) + 10
            painter.setPen(QColor("#6b7280"))
            painter.drawText(area, Qt.AlignVCenter | Qt.AlignRight, count_text)
            area.adjust(0, 0, -count_width, 0)
        x = area.left()
        height = metrics.height() + 6
        for number, (name, color) in enumerate(badges):
            remaining = len(badges) - number - 1
            reserve = metrics.horizontalAdvance(f"+{remaining}") + 9 if remaining else 0
            room = area.right() - x + 1
            if room < 24:
                break
            width = min(metrics.horizontalAdvance(name) + 14, max(20, room - reserve))
            text = metrics.elidedText(name, Qt.ElideRight, max(1, width - 14))
            rect = QRect(x, area.center().y() - height // 2, width, height)
            paint_badge(painter, rect, text, color)
            x += width + 4
            if remaining and area.right() - x + 1 < metrics.horizontalAdvance(badges[number + 1][0]) + 14:
                painter.setPen(QColor("#6b7280"))
                painter.drawText(QRect(x, area.top(), max(0, area.right() - x + 1), area.height()),
                                 Qt.AlignVCenter | Qt.AlignLeft, f"+{remaining}")
                break
        painter.restore()


class TagBadgeLabel(QLabel):
    """미리보기에서는 태그를 줄바꿈해서 그려요. 태그 문구는 일반 텍스트예요."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.names = ()
        self.colors = {}
        self.setTextFormat(Qt.PlainText)
        self.setWordWrap(True)
        self.setMinimumHeight(26)

    def show_tags(self, names, colors, empty_text):
        self.names, self.colors = tuple(names), colors or {}
        self.setText(", ".join(names) if names else empty_text)
        self.setToolTip(self.text())
        self.updateGeometry()
        self.update()

    def _rectangles(self, width):
        metrics = self.fontMetrics()
        x, y, gap = 0, 0, 4
        height = metrics.height() + 6
        for name in self.names:
            chip_width = min(max(1, width), metrics.horizontalAdvance(name) + 14)
            if x and x + chip_width > width:
                x, y = 0, y + height + gap
            yield name, QRect(x, y, chip_width, height)
            x += chip_width + gap

    def heightForWidth(self, width):
        if not self.names:
            return super().heightForWidth(width)
        return max((rect.bottom() + 1 for _, rect in self._rectangles(width)), default=26)

    def minimumSizeHint(self):
        return QSize(0, 26)

    def sizeHint(self):
        return QSize(240, self.heightForWidth(max(1, self.width())))

    def paintEvent(self, event):
        if not self.names:
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(self.font())
        for name, rect in self._rectangles(self.width()):
            text = self.fontMetrics().elidedText(name, Qt.ElideRight, max(1, rect.width() - 14))
            paint_badge(painter, rect, text, self.colors.get(name, DEFAULT_TAG_COLOR))
        painter.end()
