# -*- coding: utf-8 -*-
import os
import traceback

from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QIcon, QColor
from qgis.PyQt.QtWidgets import (
    QAction, QMessageBox, QDialog, QVBoxLayout, QComboBox,
    QDoubleSpinBox, QPushButton, QLabel, QHBoxLayout,
    QFileDialog, QLineEdit
)
from qgis.core import (
    Qgis, QgsApplication, QgsProject, QgsVectorLayer,
    QgsGeometry, QgsFeatureRequest, QgsVectorFileWriter,
    QgsFeature, QgsCoordinateTransform, QgsFillSymbol,
    QgsMarkerSymbol, QgsLineSymbol,
    QgsWkbTypes, QgsCoordinateReferenceSystem, QgsField,
    QgsFields
)
from qgis.gui import QgsMapToolEmitPoint


class SpatialBufferQueryPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dlg = None
        self.point_tool = None
        self.selected_point = None
        self.buffer_layer = None
        self.highlight_layer = None
        self.result_layer = None

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QgsApplication.getThemeIcon("/mActionBuffer.svg")
        self.action = QAction(icon, "Spatial Buffer Query Pro", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToVectorMenu("Spatial Buffer Query Pro", self.action)
        self.iface.addVectorToolBarIcon(self.action)

    def unload(self):
        if self.point_tool:
            self.iface.mapCanvas().unsetMapTool(self.point_tool)
            self.point_tool = None
        self._remove_layer(self.buffer_layer)
        self.buffer_layer = None
        self._remove_layer(self.highlight_layer)
        self.highlight_layer = None
        if self.action:
            self.iface.removePluginVectorMenu("Spatial Buffer Query Pro", self.action)
            self.iface.removeVectorToolBarIcon(self.action)

    def _remove_layer(self, layer):
        if layer and layer.id() in QgsProject.instance().mapLayers():
            QgsProject.instance().removeMapLayer(layer.id())

    def clear_results(self):
        """Xóa vùng đệm Buffer và lớp tô sáng điểm vàng, trả bản đồ về trạng thái ban đầu."""
        self._remove_layer(self.buffer_layer)
        self.buffer_layer = None
        self._remove_layer(self.highlight_layer)
        self.highlight_layer = None

        layer = self.cb_layers.currentData() if hasattr(self, "cb_layers") else None
        if layer and layer.isValid():
            layer.removeSelection()

        self.iface.mapCanvas().refresh()
        if hasattr(self, "lbl_point_status"):
            self.lbl_point_status.setText("Đã xóa vùng đệm và kết quả truy vấn.")

    def run(self):
        if self.dlg is None:
            self.dlg = QDialog(self.iface.mainWindow())
            self.dlg.setWindowTitle("Spatial Buffer Query Pro - Truy vấn không gian")
            self.dlg.setMinimumWidth(480)
            layout = QVBoxLayout(self.dlg)

            layout.addWidget(QLabel("<b>1. Chọn lớp Vector cần truy vấn:</b>"))
            self.cb_layers = QComboBox()
            layout.addWidget(self.cb_layers)

            layout.addWidget(QLabel("<b>2. Bán kính tìm kiếm (mét):</b>"))
            self.spin_radius = QDoubleSpinBox()
            self.spin_radius.setRange(0.01, 1000000)
            self.spin_radius.setDecimals(2)
            self.spin_radius.setValue(600)
            self.spin_radius.setSuffix(" m")
            layout.addWidget(self.spin_radius)

            layout.addWidget(QLabel("<b>3. Chọn tâm truy vấn:</b>"))
            self.btn_point = QPushButton("📍 Click để chọn điểm trên bản đồ")
            self.btn_point.setStyleSheet(
                "QPushButton { padding: 6px; font-weight: bold; background: #e3f2fd; border: 1px solid #90caf9; border-radius: 4px; }"
            )
            self.btn_point.clicked.connect(self.select_point)
            layout.addWidget(self.btn_point)
            self.lbl_point_status = QLabel("Chưa chọn điểm tâm.")
            self.lbl_point_status.setStyleSheet("color: #555; font-style: italic;")
            self.lbl_point_status.setWordWrap(True)
            layout.addWidget(self.lbl_point_status)

            layout.addWidget(QLabel("<b>4. File xuất kết quả (không bắt buộc):</b>"))
            file_row = QHBoxLayout()
            self.path_edit = QLineEdit()
            self.path_edit.setPlaceholderText("Đường dẫn lưu file .geojson hoặc .shp...")
            btn_browse = QPushButton("Duyệt...")
            btn_browse.clicked.connect(self.browse_export_file)
            file_row.addWidget(self.path_edit)
            file_row.addWidget(btn_browse)
            layout.addLayout(file_row)

            # Nút thực hiện & Nút xóa kết quả
            btn_row = QHBoxLayout()
            self.btn_execute = QPushButton("⚡ THỰC HIỆN TRUY VẤN VÙNG ĐỆM")
            self.btn_execute.setStyleSheet(
                "QPushButton { background: #2e7d32; color: white; font-weight: bold; padding: 10px; border-radius: 4px; font-size: 13px; }"
                "QPushButton:hover { background: #1b5e20; }"
            )
            self.btn_execute.clicked.connect(self.execute)

            self.btn_clear = QPushButton("🗑️ Xóa kết quả")
            self.btn_clear.setStyleSheet(
                "QPushButton { background: #f5f5f5; color: #333; font-weight: bold; padding: 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 12px; }"
                "QPushButton:hover { background: #e0e0e0; }"
            )
            self.btn_clear.clicked.connect(self.clear_results)

            btn_row.addWidget(self.btn_execute, stretch=3)
            btn_row.addWidget(self.btn_clear, stretch=1)
            layout.addLayout(btn_row)

            note = QLabel(
                "ℹ️ <b>Quy ước hiển thị:</b> Cột điện ban đầu là <b>chấm xanh dương</b>. "
                "Khi truy quét trong vùng đệm, các cột điện được tìm thấy sẽ chuyển thành <b>chấm vàng rực rỡ</b>."
            )
            note.setWordWrap(True)
            note.setStyleSheet("color: #0d47a1; background: #e8f5e9; padding: 7px; border-radius: 4px; font-size: 11px; margin-top: 5px;")
            layout.addWidget(note)

        self.refresh_layers()
        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()

    def refresh_layers(self):
        self.cb_layers.clear()
        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsVectorLayer) and layer.isValid():
                if layer.geometryType() != QgsWkbTypes.NullGeometry:
                    geom_tag = {
                        QgsWkbTypes.PointGeometry: "Điểm",
                        QgsWkbTypes.LineGeometry: "Đường",
                        QgsWkbTypes.PolygonGeometry: "Vùng"
                    }.get(layer.geometryType(), "Vector")
                    self.cb_layers.addItem(f"{layer.name()}  [{geom_tag}]", layer)

    def select_point(self):
        self.dlg.hide()
        self.point_tool = QgsMapToolEmitPoint(self.iface.mapCanvas())
        self.point_tool.canvasClicked.connect(self.on_point_clicked)
        self.iface.mapCanvas().setMapTool(self.point_tool)
        self.iface.messageBar().pushMessage(
            "Spatial Buffer Query Pro",
            "Click chuột vào một vị trí trên bản đồ để chọn tâm vùng Buffer.",
            level=Qgis.MessageLevel.Info,
            duration=6
        )

    def on_point_clicked(self, point, button):
        self.selected_point = point
        self.lbl_point_status.setText(
            f"Đã chọn tâm: X = {point.x():.6f}, Y = {point.y():.6f}"
        )
        if self.point_tool:
            self.iface.mapCanvas().unsetMapTool(self.point_tool)
            self.point_tool = None
        self.dlg.show()
        self.dlg.raise_()

    def browse_export_file(self):
        path, selected_filter = QFileDialog.getSaveFileName(
            self.dlg,
            "Lưu kết quả truy vấn",
            "",
            "GeoJSON (*.geojson);;ESRI Shapefile (*.shp)"
        )
        if not path:
            return
        if selected_filter.startswith("GeoJSON") and not path.lower().endswith(".geojson"):
            path += ".geojson"
        elif selected_filter.startswith("ESRI") and not path.lower().endswith(".shp"):
            path += ".shp"
        self.path_edit.setText(path)

    def _resolve_crs(self, layer):
        """
        Đảm bảo Layer và Map Canvas luôn có CRS hợp lệ.
        Nếu layer hoặc bản đồ chưa xác định CRS, tự động nhận diện WGS 84 (EPSG:4326)
        hoặc CRS của Project mà không làm gián đoạn người dùng.
        """
        project = QgsProject.instance()

        # 1. Giải quyết Layer CRS
        layer_crs = layer.crs()
        if not layer_crs.isValid():
            if project.crs().isValid():
                layer_crs = project.crs()
            else:
                ext = layer.extent()
                if -180.0 <= ext.xMinimum() <= 180.0 and -180.0 <= ext.xMaximum() <= 180.0 and \
                   -90.0 <= ext.yMinimum() <= 90.0 and -90.0 <= ext.yMaximum() <= 90.0:
                    layer_crs = QgsCoordinateReferenceSystem("EPSG:4326")
                else:
                    layer_crs = QgsCoordinateReferenceSystem("EPSG:32648")  # UTM 48N
            layer.setCrs(layer_crs)

        # 2. Giải quyết Canvas CRS
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        if not canvas_crs.isValid():
            if project.crs().isValid():
                canvas_crs = project.crs()
            else:
                canvas_crs = layer_crs
            self.iface.mapCanvas().setDestinationCrs(canvas_crs)

        return canvas_crs, layer_crs

    def _make_local_metric_crs(self, point_lonlat):
        """
        Tạo hệ tọa độ mét cục bộ quanh điểm (Azimuthal Equidistant) hoặc UTM Zone.
        Đảm bảo tính toán khoảng cách bán kính Buffer luôn chuẩn xác theo mét.
        """
        lon = point_lonlat.x()
        lat = point_lonlat.y()
        proj = (
            f"+proj=aeqd +lat_0={lat:.10f} +lon_0={lon:.10f} "
            f"+datum=WGS84 +units=m +no_defs"
        )
        crs = QgsCoordinateReferenceSystem()
        success = False
        try:
            success = crs.createFromProj(proj)
        except Exception:
            success = False

        if not success or not crs.isValid():
            zone = int((lon + 180) / 6) + 1
            epsg_code = 32600 + zone if lat >= 0 else 32700 + zone
            crs = QgsCoordinateReferenceSystem(f"EPSG:{epsg_code}")
            if not crs.isValid():
                crs = QgsCoordinateReferenceSystem("EPSG:3857")

        return crs

    def _create_result_memory_layer(self, source_layer, matched_features):
        geom_name = QgsWkbTypes.displayString(source_layer.wkbType())
        crs_authid = source_layer.crs().authid() if source_layer.crs().isValid() else "EPSG:4326"
        uri = f"{geom_name}?crs={crs_authid}"
        out = QgsVectorLayer(uri, f"KQ_{source_layer.name()}", "memory")
        if not out.isValid():
            raise Exception("Không thể khởi tạo lớp dữ liệu kết quả trong bộ nhớ.")

        provider = out.dataProvider()
        provider.addAttributes(source_layer.fields())
        out.updateFields()

        new_features = []
        for feat in matched_features:
            f = QgsFeature(out.fields())
            f.setGeometry(feat.geometry())
            f.setAttributes(feat.attributes())
            new_features.append(f)

        provider.addFeatures(new_features)
        out.updateExtents()
        return out

    def _export_layer(self, layer, path):
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.fileEncoding = "UTF-8"
        options.driverName = "GeoJSON" if path.lower().endswith(".geojson") else "ESRI Shapefile"

        result = QgsVectorFileWriter.writeAsVectorFormatV3(
            layer, path, QgsProject.instance().transformContext(), options
        )
        if result[0] != QgsVectorFileWriter.NoError:
            raise Exception(f"Xuất file thất bại: {result}")

        loaded = QgsVectorLayer(path, f"KQ_{layer.name()}", "ogr")
        if loaded.isValid():
            QgsProject.instance().addMapLayer(loaded)

    def execute(self):
        try:
            layer = self.cb_layers.currentData()
            if not layer or not layer.isValid():
                QMessageBox.warning(self.dlg, "Thiếu dữ liệu", "Vui lòng chọn một lớp Vector hợp lệ từ danh sách.")
                return

            if self.selected_point is None:
                QMessageBox.warning(self.dlg, "Thiếu tâm", "Vui lòng bấm 'Click để chọn điểm trên bản đồ' trước khi thực hiện.")
                return

            radius = float(self.spin_radius.value())
            if radius <= 0:
                QMessageBox.warning(self.dlg, "Bán kính không hợp lệ", "Bán kính tìm kiếm phải lớn hơn 0 mét.")
                return

            # Tự động nhận diện và đảm bảo tính hợp lệ của CRS
            canvas_crs, layer_crs = self._resolve_crs(layer)
            project = QgsProject.instance()

            # Chuyển điểm tâm đã click về WGS 84 (Lon, Lat)
            wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
            if canvas_crs == wgs84:
                point_lonlat = self.selected_point
            else:
                to_wgs84 = QgsCoordinateTransform(canvas_crs, wgs84, project)
                point_lonlat = to_wgs84.transform(self.selected_point)

            # Hệ tọa độ mét cục bộ quanh tâm
            metric_crs = self._make_local_metric_crs(point_lonlat)
            canvas_to_metric = QgsCoordinateTransform(canvas_crs, metric_crs, project)
            layer_to_metric = QgsCoordinateTransform(layer_crs, metric_crs, project)
            metric_to_layer = QgsCoordinateTransform(metric_crs, layer_crs, project)

            # Tạo hình học Buffer hình tròn bán kính mét
            point_metric = canvas_to_metric.transform(self.selected_point)
            buffer_metric = QgsGeometry.fromPointXY(point_metric).buffer(radius, 64)
            if buffer_metric.isNull() or buffer_metric.isEmpty():
                raise Exception("Không thể khởi tạo hình học vùng đệm Buffer.")

            # Chuyển hình học Buffer về CRS hiển thị của Layer
            buffer_for_display = QgsGeometry(buffer_metric)
            buffer_for_display.transform(metric_to_layer)

            # Vẽ lớp hiển thị vùng đệm hình tròn
            self._remove_layer(self.buffer_layer)
            authid = layer_crs.authid() if layer_crs.isValid() and layer_crs.authid() else "EPSG:4326"
            self.buffer_layer = QgsVectorLayer(
                f"Polygon?crs={authid}",
                f"Vùng Buffer bán kính {radius:g}m",
                "memory"
            )
            if not self.buffer_layer.isValid():
                raise Exception("Không thể tạo lớp hiển thị đồ họa vùng Buffer.")

            bf = QgsFeature(self.buffer_layer.fields())
            bf.setGeometry(buffer_for_display)
            self.buffer_layer.dataProvider().addFeatures([bf])
            self.buffer_layer.updateExtents()

            symbol = QgsFillSymbol.createSimple({
                "color": "244,67,54,35",
                "outline_color": "211,47,47,230",
                "outline_width": "0.75",
                "outline_width_unit": "MM",
                "outline_style": "dash"
            })
            self.buffer_layer.renderer().setSymbol(symbol)
            QgsProject.instance().addMapLayer(self.buffer_layer)

            # Thực hiện truy vấn không gian
            matched = []
            matched_ids = []
            filter_rect = buffer_for_display.boundingBox()
            request = QgsFeatureRequest().setFilterRect(filter_rect)

            for feat in layer.getFeatures(request):
                geom = feat.geometry()
                if geom is None or geom.isNull() or geom.isEmpty():
                    continue

                metric_geom = QgsGeometry(geom)
                metric_geom.transform(layer_to_metric)
                if metric_geom.intersects(buffer_metric):
                    matched.append(feat)
                    matched_ids.append(feat.id())

            # Xóa lớp highlight cũ nếu có
            self._remove_layer(self.highlight_layer)

            # Hiển thị các đối tượng được tìm thấy trong vùng đệm:
            # - Điểm (Cột điện) -> CHẤM VÀNG rực rỡ
            # - Đường (Đường phố / Dây) -> Đường viền vàng
            # - Vùng (Lô đất / Công trình) -> Vùng phủ vàng
            if matched:
                geom_type = layer.geometryType()
                if geom_type == QgsWkbTypes.PointGeometry:
                    self.highlight_layer = QgsVectorLayer(
                        f"Point?crs={authid}",
                        f"🟡 Cột điện trong vùng Buffer ({len(matched)})",
                        "memory"
                    )
                    prov = self.highlight_layer.dataProvider()
                    prov.addAttributes(layer.fields())
                    self.highlight_layer.updateFields()

                    new_feats = []
                    for feat in matched:
                        f = QgsFeature(self.highlight_layer.fields())
                        f.setGeometry(feat.geometry())
                        f.setAttributes(feat.attributes())
                        new_feats.append(f)
                    prov.addFeatures(new_feats)
                    self.highlight_layer.updateExtents()

                    # CHẤM VÀNG (Yellow dot) viền cam đậm nổi bật
                    sym_hl = QgsMarkerSymbol.createSimple({
                        "name": "circle",
                        "color": "255,214,0,255",         # Màu vàng tươi (Yellow)
                        "outline_color": "191,54,12,255",     # Viền cam đỏ tương phản cao
                        "outline_width": "0.45",
                        "size": "3.8",
                        "size_unit": "MM"
                    })
                    self.highlight_layer.renderer().setSymbol(sym_hl)
                    QgsProject.instance().addMapLayer(self.highlight_layer)

                elif geom_type == QgsWkbTypes.LineGeometry:
                    self.highlight_layer = QgsVectorLayer(
                        f"LineString?crs={authid}",
                        f"🟡 Tuyến trong vùng Buffer ({len(matched)})",
                        "memory"
                    )
                    prov = self.highlight_layer.dataProvider()
                    prov.addAttributes(layer.fields())
                    self.highlight_layer.updateFields()
                    new_feats = [QgsFeature(f) for f in matched]
                    prov.addFeatures(new_feats)
                    self.highlight_layer.updateExtents()

                    sym_hl = QgsLineSymbol.createSimple({
                        "line_color": "255,214,0,255",
                        "line_width": "1.4",
                        "line_width_unit": "MM"
                    })
                    self.highlight_layer.renderer().setSymbol(sym_hl)
                    QgsProject.instance().addMapLayer(self.highlight_layer)

                elif geom_type == QgsWkbTypes.PolygonGeometry:
                    self.highlight_layer = QgsVectorLayer(
                        f"Polygon?crs={authid}",
                        f"🟡 Lô/Công trình trong vùng Buffer ({len(matched)})",
                        "memory"
                    )
                    prov = self.highlight_layer.dataProvider()
                    prov.addAttributes(layer.fields())
                    self.highlight_layer.updateFields()
                    new_feats = [QgsFeature(f) for f in matched]
                    prov.addFeatures(new_feats)
                    self.highlight_layer.updateExtents()

                    sym_hl = QgsFillSymbol.createSimple({
                        "color": "255,235,59,110",
                        "outline_color": "255,143,0,255",
                        "outline_width": "0.8",
                        "outline_width_unit": "MM"
                    })
                    self.highlight_layer.renderer().setSymbol(sym_hl)
                    QgsProject.instance().addMapLayer(self.highlight_layer)

            # Đồng thời tô sáng (select) lớp gốc
            layer.removeSelection()
            layer.selectByIds(matched_ids)
            self.iface.mapCanvas().refresh()

            # Xuất file kết quả nếu người dùng nhập đường dẫn
            output_path = self.path_edit.text().strip()
            if output_path:
                result_layer = self._create_result_memory_layer(layer, matched)
                self._export_layer(result_layer, output_path)

            geom_name = {
                QgsWkbTypes.PointGeometry: "Điểm (Point)",
                QgsWkbTypes.LineGeometry: "Đường (Line)",
                QgsWkbTypes.PolygonGeometry: "Vùng (Polygon)"
            }.get(layer.geometryType(), "Đối tượng")

            msg = (
                f"✅ <b>Truy quét vùng đệm hoàn tất thành công!</b><br><br>"
                f"• <b>Lớp truy vấn:</b> {layer.name()}<br>"
                f"• <b>Loại hình học:</b> {geom_name}<br>"
                f"• <b>Bán kính vùng đệm:</b> {radius:g} mét<br>"
                f"• <b>Số đối tượng tìm thấy:</b> <span style='color: #d32f2f; font-weight: bold;'>{len(matched)}</span> đối tượng<br>"
                f"• <b>Hệ tọa độ (CRS):</b> {layer_crs.authid()}<br><br>"
                f"<i>Các cột điện/đối tượng trong vùng đệm đã được hiển thị bằng <b>chấm vàng</b> (và tô sáng vàng).</i>"
            )
            if output_path:
                msg += f"<br><br>📁 <b>Đã xuất file kết quả:</b> {output_path}"

            QMessageBox.information(self.dlg, "Kết quả truy vấn không gian", msg)

        except Exception as exc:
            details = traceback.format_exc()
            QMessageBox.critical(
                self.dlg,
                "Lỗi thực thi Spatial Buffer Query Pro",
                f"{exc}\n\nChi tiết kỹ thuật:\n{details}"
            )
            self.iface.messageBar().pushMessage(
                "Spatial Buffer Query Pro",
                str(exc),
                level=Qgis.MessageLevel.Critical,
                duration=10
            )
