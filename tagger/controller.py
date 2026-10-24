"""태그 버튼의 실행 흐름과 메인 화면 갱신을 연결해요."""

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QDialog, QMessageBox

from common.settings import get_body_cache_path
from tagger import storage
from tagger.dialogs import ManageTagsDialog, RemoveTagsDialog, TagColorDialog, STORAGE_ERRORS
from tagger.move_dialog import PathMoveDialog
from tagger.path_tracking import resolve_path_moves


class TagController(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.db_path = get_body_cache_path()
        self.colors = {}
        self.tags_by_id = {}
        window.tag_bar.attach_requested.connect(self.attach_selected)
        window.tag_bar.detach_requested.connect(self.detach_selected)
        window.tag_sidebar.manage_requested.connect(self.manage_tags)
        window.tag_sidebar.tag_activated.connect(self.show_tag_documents)
        window.tag_sidebar.color_requested.connect(self.change_color)
        window.results.table.hits_changed.connect(self.refresh_file_tags)
        window.results.table.current_hit_changed.connect(self.show_preview_tags)
        self.refresh()

    def selected_paths(self):
        return [hit.path for hit in self.window.results.table.checked_hits()]

    def refresh(self, reload_results=True):
        try:
            tags = storage.show_tag(self.db_path)
        except STORAGE_ERRORS as error:
            self.window.tag_bar.show_error(error)
            self.window.status_label.setText(f"태그를 읽지 못했어요: {error}")
            return
        self.window.tag_bar.show_error("")
        self.colors = {tag.name: tag.color for tag in tags}
        self.tags_by_id = {tag.id: tag for tag in tags}
        active_id = self.window.active_tag_id
        self.window.tag_sidebar.show_tags(tags, active_id)
        if active_id is not None and active_id not in self.tags_by_id:
            self.window.active_tag_id = None
            self.window.results.set_tag_filter(None)
            self.window.results.show_hits([], [])
            self.window.status_label.setText("선택한 태그가 삭제됐어요.")
        elif active_id is not None and reload_results:
            self.window.run_search(active_id)
            return
        self.refresh_file_tags()

    def refresh_file_tags(self):
        table = self.window.results.table
        try:
            tags = storage.read_file_tags([hit.path for hit in table.hits], self.db_path)
        except STORAGE_ERRORS as error:
            table.show_tags({})
            self.show_preview_tags(self.window.preview.hit)
            self.window.tag_bar.show_error(error)
            self.window.status_label.setText(f"태그를 읽지 못했어요: {error}")
            return
        self.window.tag_bar.show_error("")
        table.show_tags(tags, self.colors)
        self.show_preview_tags(self.window.preview.hit)

    def show_preview_tags(self, hit):
        names = self.window.results.table.tags_by_path.get(hit.path, ()) if hit else ()
        self.window.preview.show_tags(names, self.colors)

    def attach_selected(self):
        bar = self.window.tag_bar
        paths = self.selected_paths()
        names = [name.strip() for name in bar.tag_input.text().split(",") if name.strip()]
        try:
            count = storage.attach_tags(paths, names, db_path=self.db_path)
        except STORAGE_ERRORS as error:
            QMessageBox.warning(self.window, "태그 부착", str(error))
            return
        bar.tag_input.clear()
        self.refresh()
        self.window.status_label.setText(f"선택한 파일 {len(paths)}개에 태그를 부착했어요. 새로 붙인 태그 {count}건")

    def detach_selected(self):
        paths = self.selected_paths()
        if not paths:
            return
        try:
            tags = storage.show_tag(self.db_path, paths=paths)
            if not tags:
                QMessageBox.information(self.window, "태그 제거", "선택한 파일에 붙은 태그가 없어요.")
                return
            dialog = RemoveTagsDialog(tags, len(paths), self.window)
            try:
                if dialog.exec() != QDialog.Accepted:
                    return
                ids = dialog.choices.checked_ids()
            finally:
                dialog.deleteLater()
            count = storage.detach_tags(paths, ids, self.db_path)
        except STORAGE_ERRORS as error:
            QMessageBox.warning(self.window, "태그 제거", str(error))
            return
        self.refresh()
        self.window.status_label.setText(f"선택한 파일에서 태그 {count}건을 제거했어요.")

    def confirm_path_moves(self, candidates):
        if not candidates:
            return
        dialog = PathMoveDialog(candidates, self.window)
        try:
            if dialog.exec() != QDialog.Accepted:
                return
            choices = dialog.selected_choices()
            transfer = dialog.action == "transfer"
            try:
                count = resolve_path_moves(choices, transfer=transfer, db_path=self.db_path)
            except STORAGE_ERRORS as error:
                QMessageBox.warning(self.window, "경로 변경 처리", str(error))
                return
        finally:
            dialog.deleteLater()
        self.refresh()
        detail = f"{count}개 파일의 태그를 옮겼어요." if transfer else f"이전 경로 {count}개의 DB 기록을 삭제했어요."
        self.window.status_label.setText(self.window.status_label.text() + " · " + detail)

    def show_tag_documents(self, tag_id):
        self.window.run_search(tag_id)

    def change_color(self, tag_id):
        tag = self.tags_by_id.get(tag_id)
        if tag is None:
            return
        dialog = TagColorDialog(tag, self.window)
        try:
            if dialog.exec() != QDialog.Accepted:
                return
            color = dialog.selectedColor().name()
            try:
                storage.set_tag_color(tag_id, color, self.db_path)
            except STORAGE_ERRORS as error:
                QMessageBox.warning(self.window, "태그 색 변경", str(error))
                return
        finally:
            dialog.deleteLater()
        self.refresh(reload_results=False)

    def manage_tags(self):
        dialog = ManageTagsDialog(self.db_path, self.window)
        dialog.changed.connect(self.refresh)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()
