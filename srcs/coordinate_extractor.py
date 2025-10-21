# vision_align_v3.py
"""
VisionAlign v3
- Curseur de clic pendant calibration
- 3 points pour pièce et cylindre, 2 pour carte bancaire
- Relie automatiquement les points : rectangle (carte) ou cercle (pièce/cylindre)
- Grille visible uniquement après calibration
- Rotation possible uniquement après calibration, puis verrouillable
"""

import sys, math
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QLabel, QGraphicsView, QGraphicsScene,
    QGraphicsPixmapItem, QFileDialog, QVBoxLayout, QWidget, QPushButton,
    QSlider, QComboBox, QHBoxLayout, QMessageBox
)
from PyQt5.QtGui import (
    QPixmap, QPainter, QPen, QColor, QTransform, QBrush, QCursor, QPolygonF
)
from PyQt5.QtCore import Qt, QPointF, QRectF

# --- Références connues (type, dimensions mm) ---
PRESETS = {
    "Carte bancaire (85.60 x 53.98 mm)": ("card", (85.60, 53.98)),
    "Pièce 1€ (23.25 mm)": ("coin", 23.25),
    "Pièce 2€ (25.75 mm)": ("coin", 25.75),
    "Cylindre (17 mm)": ("cylinder", 17.0),
}

def distance(a, b):
    return math.hypot(a.x()-b.x(), a.y()-b.y())


class GridView(QGraphicsView):
    """Vue personnalisée qui dessine la grille seulement après calibration"""
    def __init__(self, scene):
        super().__init__(scene)
        self.px_per_mm = None
        self.grid_opacity = 0.25
        self.axis_color_x = QColor(50, 120, 200)
        self.axis_color_y = QColor(200, 50, 50)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(Qt.white)

    def set_scale(self, px_per_mm):
        self.px_per_mm = px_per_mm
        self.viewport().update()

    def drawBackground(self, painter, rect):
        if not self.px_per_mm:
            return
        left, right = int(rect.left()), int(rect.right())
        top, bottom = int(rect.top()), int(rect.bottom())
        px_per_tenth = self.px_per_mm * 0.1
        if px_per_tenth < 0.5:
            return

        painter.save()
        painter.setOpacity(self.grid_opacity)
        pen_minor = QPen(QColor(220, 220, 220), 0)
        pen_major = QPen(QColor(180, 180, 180), 0)

        start_x = math.floor(left / px_per_tenth) * px_per_tenth
        x = start_x
        while x < right:
            painter.setPen(pen_major if abs(x % (self.px_per_mm)) < 0.1 else pen_minor)
            painter.drawLine(x, top, x, bottom)
            x += px_per_tenth

        start_y = math.floor(top / px_per_tenth) * px_per_tenth
        y = start_y
        while y < bottom:
            painter.setPen(pen_major if abs(y % (self.px_per_mm)) < 0.1 else pen_minor)
            painter.drawLine(left, y, right, y)
            y += px_per_tenth
        painter.restore()

        # axes X/Y
        painter.setPen(QPen(self.axis_color_y, 2))
        painter.drawLine(0, top, 0, bottom)
        painter.setPen(QPen(self.axis_color_x, 2))
        painter.drawLine(left, 0, right, 0)


class ImageAligner(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VisionAlign - Calibration et Grille v3")
        self.setGeometry(100, 100, 1100, 800)

        self.scene = QGraphicsScene()
        self.view = GridView(self.scene)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.view.viewport().installEventFilter(self)

        self.load_btn = QPushButton("📂 Charger une image")
        self.calib_combo = QComboBox()
        for k in PRESETS.keys():
            self.calib_combo.addItem(k)
        self.calib_btn = QPushButton("Démarrer calibration")
        self.calib_btn.setCheckable(True)
        self.ok_btn = QPushButton("OK")
        self.ok_btn.setEnabled(False)

        self.rotate_slider = QSlider(Qt.Horizontal)
        self.rotate_slider.setRange(-180, 180)
        self.rotate_slider.setEnabled(False)
        self.rotate_slider.valueChanged.connect(self.rotate_image)

        self.lock_btn = QPushButton("🔒 Verrouiller rotation")
        self.lock_btn.setEnabled(False)
        self.lock_btn.clicked.connect(self.lock_rotation)

        top = QHBoxLayout()
        top.addWidget(self.load_btn)
        top.addWidget(QLabel("Calibration :"))
        top.addWidget(self.calib_combo)
        top.addWidget(self.calib_btn)
        top.addWidget(self.ok_btn)
        top.addStretch()
        top.addWidget(QLabel("Rotation :"))
        top.addWidget(self.rotate_slider)
        top.addWidget(self.lock_btn)

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(self.view)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.load_btn.clicked.connect(self.load_image)
        self.calib_btn.toggled.connect(self.toggle_calibration)
        self.ok_btn.clicked.connect(self.finish_calibration)

        self.image_item = None
        self.calibrating = False
        self.points = []
        self.markers = []
        self.px_per_mm = None
        self.rotation_locked = False

    # --- Chargement image ---
    def load_image(self):
        path, _ = QFileDialog.getOpenFileName(self, "Ouvrir image", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.warning(self, "Erreur", "Impossible de charger l’image.")
            return
        self.scene.clear()
        self.image_item = QGraphicsPixmapItem(pixmap)
        self.image_item.setOffset(-pixmap.width()/2, -pixmap.height()/2)
        self.scene.addItem(self.image_item)
        self.scene.setSceneRect(-pixmap.width()/2, -pixmap.height()/2,
                                pixmap.width(), pixmap.height())
        self.view.centerOn(0, 0)
        self.view.set_scale(None)
        self.rotate_slider.setEnabled(False)
        self.lock_btn.setEnabled(False)

    # --- Calibration ---
    def toggle_calibration(self, active):
        self.calibrating = active
        if active:
            self.points.clear()
            self.clear_markers()
            self.ok_btn.setEnabled(False)
            # curseur : icône "main qui clique"
            self.view.setCursor(QCursor(Qt.PointingHandCursor))
        else:
            self.view.setCursor(QCursor(Qt.ArrowCursor))

    def eventFilter(self, source, event):
        if event.type() == event.MouseButtonPress and source is self.view.viewport():
            if self.calibrating and event.button() == Qt.LeftButton:
                scene_pos = self.view.mapToScene(event.pos())
                marker = self.scene.addEllipse(scene_pos.x()-4, scene_pos.y()-4, 8, 8,
                                               QPen(Qt.green), QBrush(QColor(0,255,0,120)))
                self.markers.append(marker)
                self.points.append(scene_pos)
                self.update_ok_button()
        return super().eventFilter(source, event)

    def update_ok_button(self):
        preset = PRESETS[self.calib_combo.currentText()]
        kind = preset[0]
        needed = 2 if kind == "card" else 3
        self.ok_btn.setEnabled(len(self.points) >= needed)

    def clear_markers(self):
        for m in self.markers:
            self.scene.removeItem(m)
        self.markers.clear()

    def finish_calibration(self):
        preset = PRESETS[self.calib_combo.currentText()]
        kind, ref = preset
        try:
            if kind == "card":
                if len(self.points) < 2:
                    QMessageBox.warning(self, "Calibration", "2 points nécessaires pour la carte.")
                    return
                p1, p2 = self.points
                width_px = distance(p1, p2)
                real_w = ref[0]  # on prend la largeur
                px_per_mm = width_px / real_w
                # dessin rectangle
                rect = QRectF(p1, p2)
                self.scene.addRect(rect, QPen(Qt.red, 2, Qt.DashLine))
            elif kind in ("coin", "cylinder"):
                if len(self.points) < 3:
                    QMessageBox.warning(self, "Calibration", "3 points nécessaires pour ce mode.")
                    return
                pts = self.points[:3]
                center_x = sum(p.x() for p in pts) / 3
                center_y = sum(p.y() for p in pts) / 3
                avg_r = sum(distance(QPointF(center_x, center_y), p) for p in pts) / 3
                px_per_mm = (avg_r * 2) / ref
                # dessin cercle
                self.scene.addEllipse(center_x-avg_r, center_y-avg_r, avg_r*2, avg_r*2,
                                      QPen(Qt.red, 2, Qt.DashLine))
            else:
                QMessageBox.warning(self, "Erreur", "Type inconnu.")
                return
        except Exception as e:
            QMessageBox.critical(self, "Erreur", str(e))
            return

        self.px_per_mm = px_per_mm
        self.view.set_scale(px_per_mm)
        self.calib_btn.setChecked(False)
        self.calibrating = False
        self.view.setCursor(QCursor(Qt.ArrowCursor))
        QMessageBox.information(self, "Calibration", f"Calibration réussie : {px_per_mm:.3f} px/mm")

        # activer rotation
        self.rotate_slider.setEnabled(True)
        self.lock_btn.setEnabled(True)

    # --- Rotation ---
    def rotate_image(self):
        if not self.image_item or not self.px_per_mm or self.rotation_locked:
            return
        angle = self.rotate_slider.value()
        t = QTransform()
        t.rotate(angle)
        self.image_item.setTransform(t)

    def lock_rotation(self):
        self.rotation_locked = True
        self.rotate_slider.hide()
        self.lock_btn.hide()
        QMessageBox.information(self, "Rotation verrouillée", "Rotation verrouillée et contrôles retirés.")


# --- Zoom molette ---
    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            # Ctrl + molette → zoom
            zoom_factor = 1.25 if event.angleDelta().y() > 0 else 0.8
            self.scale(zoom_factor, zoom_factor)
            self._zoom *= zoom_factor
        else:
            super().wheelEvent(event)

    def reset_zoom(self):
        self.resetTransform()
        self._zoom = 1.0


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = ImageAligner()
    win.show()
    sys.exit(app.exec_())
