/** @format */

(function () {
  "use strict";

  var root = document.documentElement;
  var buttons = Array.prototype.slice.call(
    document.querySelectorAll(".report-theme-button[data-theme-mode]")
  );
  var validModes = ["light", "dark", "auto"];
  var mode = root.dataset.themeMode || "auto";
  var colorSchemeQuery = window.matchMedia
    ? window.matchMedia("(prefers-color-scheme: dark)")
    : null;
  var stylePicker = document.getElementById("map-style");
  var exportButton = document.querySelector("[data-export-report]");

  if (exportButton) {
    exportButton.addEventListener("click", function () {
      var html = "<!DOCTYPE html>\n" + document.documentElement.outerHTML;
      var blob = new Blob([html], { type: "text/html;charset=utf-8" });
      var objectUrl = URL.createObjectURL(blob);
      var link = document.createElement("a");
      link.href = objectUrl;
      link.download =
        exportButton.dataset.exportFilename || "mapping-momentum-report.html";
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(function () {
        URL.revokeObjectURL(objectUrl);
      }, 0);
    });
  }

  function resolveTheme() {
    if (mode !== "auto") return mode;
    return colorSchemeQuery && colorSchemeQuery.matches ? "dark" : "light";
  }

  function syncMapStyle(theme) {
    var preferredStyle = theme === "dark" ? "fiord" : "positron";
    if (!stylePicker || stylePicker.value === preferredStyle) return;
    stylePicker.value = preferredStyle;
    stylePicker.dispatchEvent(new Event("change"));
  }

  function syncButtons() {
    buttons.forEach(function (button) {
      var selected = button.dataset.themeMode === mode;
      button.setAttribute("aria-pressed", String(selected));
    });
  }

  function applyTheme(syncMap) {
    var theme = resolveTheme();
    root.dataset.themeMode = mode;
    root.dataset.theme = theme;
    root.dataset.bsTheme = theme;
    syncButtons();
    if (syncMap) {
      syncMapStyle(root.dataset.theme);
      syncMapStyle(document.documentElement.dataset.theme);
    }
  }

  buttons.forEach(function (button) {
    button.addEventListener("click", function () {
      var nextMode = button.dataset.themeMode;
      if (validModes.indexOf(nextMode) === -1) return;

      mode = nextMode;
      try {
        window.localStorage.setItem("mapping-momentum-theme-mode", mode);
      } catch (error) {
        console.warn("Theme preference could not be saved.", error);
      }

      var nextTheme = resolveTheme();
      applyTheme(false);
      syncMapStyle(nextTheme);
    });
  });

  if (colorSchemeQuery) {
    var onColorSchemeChange = function () {
      if (mode === "auto") applyTheme(true);
    };
    if (typeof colorSchemeQuery.addEventListener === "function") {
      colorSchemeQuery.addEventListener("change", onColorSchemeChange);
    } else if (typeof colorSchemeQuery.addListener === "function") {
      colorSchemeQuery.addListener(onColorSchemeChange);
    }
  }

  var reportUi = window.MappingMomentumReport || {};
  window.MappingMomentumReport = reportUi;

  var knownCategoryShapes = {
    "bus stops": "triangle",
    crossings: "diamond",
    curbs: "square",
    sidewalks: "circle",
    intersections: "pentagon",
    "street lamps": "star",
    unknown: "hexagon",
    "(unknown)": "hexagon",
    uncategorized: "hexagon",
  };

  function displayCategory(category) {
    return typeof category === "string" && category.trim()
      ? category.trim()
      : "Uncategorized";
  }

  function categoryShapeMap(categories) {
    var labelsByCategory = new Map();
    (categories || []).forEach(function (category) {
      var key = typeof category === "string" && category.trim() ? category : "";
      labelsByCategory.set(key, displayCategory(key));
    });

    var shapeMap = Object.create(null);
    var fallbackCategories = [];
    var usedShapes = new Set();
    Array.from(labelsByCategory.entries())
      .sort(function (left, right) {
        return left[1].localeCompare(right[1]);
      })
      .forEach(function (entry) {
        var normalized = entry[1].toLowerCase();
        var knownShape = Object.prototype.hasOwnProperty.call(
          knownCategoryShapes,
          normalized
        )
          ? knownCategoryShapes[normalized]
          : null;
        if (knownShape && !usedShapes.has(knownShape)) {
          shapeMap[entry[0]] = knownShape;
          usedShapes.add(knownShape);
        } else {
          fallbackCategories.push(entry[0]);
        }
      });

    fallbackCategories.forEach(function (category, index) {
      shapeMap[category] = "polygon-" + (7 + index);
    });
    return shapeMap;
  }

  function regularPolygonPoints(sides, radius, rotation) {
    var points = [];
    for (var index = 0; index < sides; index += 1) {
      var angle = rotation + (index * Math.PI * 2) / sides;
      points.push(
        (16 + Math.cos(angle) * radius).toFixed(2) +
          "," +
          (16 + Math.sin(angle) * radius).toFixed(2)
      );
    }
    return points.join(" ");
  }

  function starPoints(radius, innerRadius) {
    var points = [];
    for (var index = 0; index < 10; index += 1) {
      var angle = -Math.PI / 2 + (index * Math.PI) / 5;
      var currentRadius = index % 2 === 0 ? radius : innerRadius;
      points.push(
        (16 + Math.cos(angle) * currentRadius).toFixed(2) +
          "," +
          (16 + Math.sin(angle) * currentRadius).toFixed(2)
      );
    }
    return points.join(" ");
  }

  function polygonSides(shape) {
    if (shape === "triangle") return 3;
    if (shape === "diamond") return 4;
    if (shape === "pentagon") return 5;
    if (shape === "hexagon") return 6;
    var match = /^polygon-(\d+)$/.exec(shape);
    return match ? Math.max(3, Number(match[1])) : 6;
  }

  function makeShapePath(shape, color) {
    var svgNamespace = "http://www.w3.org/2000/svg";
    var node;
    if (shape === "circle") {
      node = document.createElementNS(svgNamespace, "circle");
      node.setAttribute("cx", "16");
      node.setAttribute("cy", "16");
      node.setAttribute("r", "11.5");
    } else if (shape === "square") {
      node = document.createElementNS(svgNamespace, "rect");
      node.setAttribute("x", "4.5");
      node.setAttribute("y", "4.5");
      node.setAttribute("width", "23");
      node.setAttribute("height", "23");
      node.setAttribute("rx", "1.5");
    } else if (shape === "star") {
      node = document.createElementNS(svgNamespace, "polygon");
      node.setAttribute("points", starPoints(13, 5.8));
    } else if (shape === "cross") {
      node = document.createElementNS(svgNamespace, "path");
      node.setAttribute("d", "M11 3h10v8h8v10h-8v8H11v-8H3V11h8z");
    } else {
      node = document.createElementNS(svgNamespace, "polygon");
      node.setAttribute(
        "points",
        regularPolygonPoints(polygonSides(shape), 12, -Math.PI / 2)
      );
    }

    node.setAttribute("fill", color || "#5f22c9");
    node.setAttribute("stroke", "currentColor");
    node.setAttribute("stroke-width", "2.5");
    node.setAttribute("stroke-linejoin", "round");
    return node;
  }

  reportUi.renderMapLegend = function (markers, colorForCategory) {
    var list = document.getElementById("map-legend-items");
    if (!list) return categoryShapeMap([]);

    while (list.firstChild) list.removeChild(list.firstChild);

    var categories = new Map();
    var hasNotes = false;
    (markers || []).forEach(function (marker) {
      if (!marker) return;
      if (marker.kind === "note") {
        hasNotes = true;
        return;
      }

      var category = typeof marker.category === "string" ? marker.category : "";
      var key = category.trim() ? category : "";
      categories.set(key, displayCategory(key));
    });

    var shapes = categoryShapeMap(Array.from(categories.keys()));

    function appendItem(label, color, shape) {
      var item = document.createElement("li");
      item.className = "map-legend-item";

      var swatch = document.createElementNS(
        "http://www.w3.org/2000/svg",
        "svg"
      );
      swatch.classList.add("map-legend-swatch");
      swatch.setAttribute("viewBox", "0 0 32 32");
      swatch.setAttribute("aria-hidden", "true");
      swatch.setAttribute("focusable", "false");
      swatch.dataset.shape = shape;
      swatch.appendChild(makeShapePath(shape, color));

      var text = document.createElement("span");
      text.textContent = label;
      item.appendChild(swatch);
      item.appendChild(text);
      list.appendChild(item);
    }

    Array.from(categories.entries())
      .sort(function (left, right) {
        return left[1].localeCompare(right[1]);
      })
      .forEach(function (entry) {
        appendItem(entry[1], colorForCategory(entry[0]), shapes[entry[0]]);
      });

    if (hasNotes) appendItem("Notes", "#6c757d", "cross");

    if (list.childElementCount === 0) {
      var emptyItem = document.createElement("li");
      emptyItem.className = "map-legend-empty";
      emptyItem.textContent = "No map locations";
      list.appendChild(emptyItem);
    }

    return shapes;
  };

  reportUi.markerIconName = function (shape) {
    return "mm-report-marker-" + shape;
  };

  function markerShapePoints(shape) {
    if (shape === "square") {
      return [
        [4.5, 4.5],
        [27.5, 4.5],
        [27.5, 27.5],
        [4.5, 27.5],
      ];
    }
    if (shape === "cross") {
      return [
        [12, 4],
        [20, 4],
        [20, 12],
        [28, 12],
        [28, 20],
        [20, 20],
        [20, 28],
        [12, 28],
        [12, 20],
        [4, 20],
        [4, 12],
        [12, 12],
      ];
    }
    if (shape === "star") {
      return starPoints(12, 5.2)
        .split(" ")
        .map(function (point) {
          return point.split(",").map(Number);
        });
    }
    return regularPolygonPoints(polygonSides(shape), 12, -Math.PI / 2)
      .split(" ")
      .map(function (point) {
        return point.split(",").map(Number);
      });
  }

  function signedPolygonDistance(x, y, points) {
    var inside = false;
    var minDistanceSquared = Infinity;

    for (var index = 0; index < points.length; index += 1) {
      var first = points[index];
      var second = points[(index + 1) % points.length];
      var edgeX = second[0] - first[0];
      var edgeY = second[1] - first[1];
      var edgeLengthSquared = edgeX * edgeX + edgeY * edgeY;
      var along = edgeLengthSquared
        ? Math.max(
            0,
            Math.min(
              1,
              ((x - first[0]) * edgeX + (y - first[1]) * edgeY) /
                edgeLengthSquared
            )
          )
        : 0;
      var nearestX = first[0] + along * edgeX;
      var nearestY = first[1] + along * edgeY;
      var deltaX = x - nearestX;
      var deltaY = y - nearestY;
      minDistanceSquared = Math.min(
        minDistanceSquared,
        deltaX * deltaX + deltaY * deltaY
      );

      if (first[1] > y !== second[1] > y) {
        var crossingX =
          first[0] + ((y - first[1]) * edgeX) / (second[1] - first[1]);
        if (x < crossingX) inside = !inside;
      }
    }

    var distance = Math.sqrt(minDistanceSquared);
    return inside ? distance : -distance;
  }

  function createSdfMarkerImage(shape) {
    var size = 96;
    var sdfRange = 16;
    var data = new Uint8Array(size * size * 4);
    var points = shape === "circle" ? null : markerShapePoints(shape);

    for (var y = 0; y < size; y += 1) {
      for (var x = 0; x < size; x += 1) {
        var shapeX = (x + 0.5) / 2 - 8;
        var shapeY = (y + 0.5) / 2 - 8;
        var distance =
          shape === "circle"
            ? (11.5 - Math.hypot(shapeX - 16, shapeY - 16)) * 2
            : signedPolygonDistance(shapeX, shapeY, points) * 2;
        var alpha = Math.max(0, Math.min(1, 0.5 + distance / sdfRange));
        var offset = (y * size + x) * 4;
        data[offset] = 255;
        data[offset + 1] = 255;
        data[offset + 2] = 255;
        data[offset + 3] = Math.round(alpha * 255);
      }
    }

    return { width: size, height: size, data: data };
  }

  reportUi.registerMarkerImages = function (map, markerFeatures) {
    var shapes = new Set();
    ((markerFeatures && markerFeatures.features) || []).forEach(
      function (feature) {
        if (feature && feature.properties && feature.properties.shape) {
          shapes.add(feature.properties.shape);
        }
      }
    );

    shapes.forEach(function (shape) {
      if (shape === "circle") return;
      var imageName = reportUi.markerIconName(shape);
      if (map.hasImage(imageName)) return;
      map.addImage(imageName, createSdfMarkerImage(shape), {
        pixelRatio: 2,
        sdf: true,
      });
    });
  };

  reportUi.enableMapResize = function (map) {
    var wrapper = document.getElementById("map-wrapper");
    var handle = document.getElementById("map-resize-handle");
    if (!wrapper || !handle) return;

    var minHeight = 280;
    var pointerStartY = null;
    var pointerId = null;
    var startHeight = 0;
    var resizeFrame = null;

    function maxHeight() {
      return Math.max(minHeight, Math.floor(window.innerHeight * 0.8));
    }

    function syncAria() {
      var maximum = maxHeight();
      var current = Math.round(wrapper.getBoundingClientRect().height);
      handle.setAttribute("aria-valuemin", String(minHeight));
      handle.setAttribute("aria-valuemax", String(maximum));
      handle.setAttribute("aria-valuenow", String(Math.min(current, maximum)));
    }

    function requestMapResize() {
      if (!map || resizeFrame !== null) return;
      resizeFrame = window.requestAnimationFrame(function () {
        resizeFrame = null;
        map.resize();
      });
    }

    function setHeight(height) {
      var nextHeight = Math.round(
        Math.max(minHeight, Math.min(maxHeight(), height))
      );
      wrapper.style.setProperty("--mm-map-height", nextHeight + "px");
      syncAria();
      requestMapResize();
    }

    function finishPointerResize(event) {
      if (pointerId === null || (event && event.pointerId !== pointerId))
        return;
      var finishedPointerId = pointerId;
      pointerId = null;
      pointerStartY = null;
      if (
        handle.hasPointerCapture &&
        handle.hasPointerCapture(finishedPointerId)
      ) {
        handle.releasePointerCapture(finishedPointerId);
      }
    }

    handle.addEventListener("pointerdown", function (event) {
      if (wrapper.classList.contains("map-expanded")) return;
      if (event.pointerType === "mouse" && event.button !== 0) return;

      event.preventDefault();
      pointerId = event.pointerId;
      pointerStartY = event.clientY;
      startHeight = wrapper.getBoundingClientRect().height;
      if (handle.setPointerCapture) handle.setPointerCapture(pointerId);
    });

    handle.addEventListener("pointermove", function (event) {
      if (pointerId !== event.pointerId || pointerStartY === null) return;
      event.preventDefault();
      setHeight(startHeight + event.clientY - pointerStartY);
    });

    handle.addEventListener("pointerup", finishPointerResize);
    handle.addEventListener("pointercancel", finishPointerResize);
    handle.addEventListener("lostpointercapture", function () {
      pointerId = null;
      pointerStartY = null;
    });

    handle.addEventListener("keydown", function (event) {
      if (wrapper.classList.contains("map-expanded")) return;

      var current = wrapper.getBoundingClientRect().height;
      var nextHeight;
      if (event.key === "ArrowUp") nextHeight = current - 20;
      else if (event.key === "ArrowDown") nextHeight = current + 20;
      else if (event.key === "Home") nextHeight = minHeight;
      else if (event.key === "End") nextHeight = maxHeight();
      else return;

      event.preventDefault();
      setHeight(nextHeight);
    });

    window.addEventListener("resize", function () {
      syncAria();
      requestMapResize();
    });
    syncAria();
  };

  applyTheme(true);
})();
