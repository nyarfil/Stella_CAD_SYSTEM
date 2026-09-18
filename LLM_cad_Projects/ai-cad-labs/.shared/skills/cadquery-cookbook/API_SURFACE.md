# CadQuery API Surface: Complete Method Reference

> **Purpose:** Definitive list of every public method on Workplane, Assembly, and Sketch.
> If a method is NOT listed here, it does NOT exist. Do not hallucinate methods.
>
> Source: Extracted from `cadquery/cadquery/cq.py`, `assembly.py`, `sketch.py`

---

## Workplane Class (112 Public Methods)

### Stack/Selection Management
| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `tag` | `(name: str)` | `T` | Tags the current CQ object for later reference |
| `all` | `()` | `List[T]` | Return a list of all CQ objects on the stack |
| `size` | `()` | `int` | Return the number of objects on the stack |
| `vals` | `()` | `List[CQObject]` | Get the values in the current list |
| `val` | `()` | `CQObject` | Return the first value on the stack |
| `first` | `()` | `T` | Return the first item on the stack |
| `item` | `(i: int)` | `T` | Return the ith item on the stack |
| `last` | `()` | `T` | Return the last item on the stack |
| `end` | `(n: int = 1)` | `Workplane` | Return the nth parent of this CQ element |
| `add` | `(obj)` | `T` | Adds an object or list of objects to the stack |
| `filter` | `(f: Callable)` | `T` | Filter items using a boolean predicate |
| `map` | `(f: Callable)` | `T` | Apply a callable to every item separately |
| `apply` | `(f: Callable)` | `T` | Apply a callable to all items at once |
| `sort` | `(key: Callable)` | `T` | Sort items using a callable |
| `invoke` | `(f)` | `T` | Invoke a callable mapping Workplane to Workplane |

### Shape Selection
| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `faces` | `(selector=None, tag=None)` | `T` | Select faces, optionally filtering by selector |
| `edges` | `(selector=None, tag=None)` | `T` | Select edges, optionally filtering |
| `vertices` | `(selector=None, tag=None)` | `T` | Select vertices, optionally filtering |
| `wires` | `(selector=None, tag=None)` | `T` | Select wires, optionally filtering |
| `solids` | `(selector=None, tag=None)` | `T` | Select solids, optionally filtering |
| `shells` | `(selector=None, tag=None)` | `T` | Select shells, optionally filtering |
| `compounds` | `(selector=None, tag=None)` | `T` | Select compounds, optionally filtering |
| `ancestors` | `(kind: Shapes, tag=None)` | `T` | Select topological ancestors |
| `siblings` | `(kind: Shapes, level=1, tag=None)` | `T` | Select topological siblings |

### Workplane Navigation
| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `workplane` | `(offset=0.0, invert=False, centerOption='ProjectedOrigin', origin=None)` | `T` | Creates a new 2D workplane relative to first face on stack |
| `copyWorkplane` | `(obj: T)` | `T` | Copies the workplane from obj |
| `workplaneFromTagged` | `(name: str)` | `Workplane` | Copies workplane from a tagged parent |
| `transformed` | `(rotate=(0,0,0), offset=(0,0,0))` | `T` | Create new workplane with rotation/offset transforms |
| `center` | `(x: float, y: float)` | `T` | Shift local coordinates to specified location |
| `findSolid` | `(searchStack=True, searchParents=True)` | `Solid/Compound` | Finds the first solid object in the chain |
| `newObject` | `(objlist: Iterable)` | `T` | Create a new workplane object from this one |
| `toOCC` | `()` | `Any` | Directly returns the wrapped OCCT object |

### 3D Primitives
| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `box` | `(length, width, height, centered=True, combine=True, clean=True)` | `T` | 3D box with specified dimensions |
| `sphere` | `(radius, direct=(0,0,1), angle1=-90, angle2=90, angle3=360, centered=True, combine=True, clean=True)` | `T` | 3D sphere with specified radius |
| `cylinder` | `(height, radius, direct=Vector(0,0,1), angle=360, centered=True, combine=True, clean=True)` | `T` | Cylinder with specified radius and height |
| `wedge` | `(dx, dy, dz, xmin, zmin, xmax, zmax, pnt=(0,0,0), dir=(0,0,1), centered=True, combine=True, clean=True)` | `T` | 3D wedge with specified dimensions |
| `text` | `(txt, fontsize, distance, combine='cut', clean=True, font='Arial', fontPath=None, kind='regular', halign='center', valign='center')` | `T` | 3D text |

### 2D Shapes (Sketch Primitives)
| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `rect` | `(xLen, yLen, centered=True, forConstruction=False)` | `T` | Rectangle for each item on stack |
| `circle` | `(radius, forConstruction=False)` | `T` | Circle for each item on stack |
| `ellipse` | `(x_radius, y_radius, rotation_angle=0.0, forConstruction=False)` | `T` | Ellipse for each item on stack |
| `polygon` | `(nSides, diameter, forConstruction=False, circumscribed=True)` | `T` | Regular polygon |
| `polyline` | `(listOfXYTuple, forConstruction=False, includeCurrent=False)` | `T` | Polyline from point list |
| `slot2D` | `(length, diameter, angle=0)` | `T` | Rounded slot shape |

### 2D Drawing (Lines and Curves)
| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `lineTo` | `(x, y, forConstruction=False)` | `T` | Line to absolute point |
| `line` | `(xDist, yDist, forConstruction=False)` | `T` | Line using relative coordinates |
| `vLine` | `(distance, forConstruction=False)` | `T` | Vertical line |
| `hLine` | `(distance, forConstruction=False)` | `T` | Horizontal line |
| `vLineTo` | `(yCoord, forConstruction=False)` | `T` | Vertical line to Y coordinate |
| `hLineTo` | `(xCoord, forConstruction=False)` | `T` | Horizontal line to X coordinate |
| `polarLine` | `(distance, angle, forConstruction=False)` | `T` | Line at angle from current point |
| `polarLineTo` | `(distance, angle, forConstruction=False)` | `T` | Line to polar coordinates |
| `moveTo` | `(x=0, y=0)` | `T` | Move without drawing |
| `move` | `(xDist=0, yDist=0)` | `T` | Relative move without drawing |
| `spline` | `(listOfXYTuple, tangents=None, periodic=False, parameters=None, scale=False, tol=None, forConstruction=False, includeCurrent=False, makeWire=False)` | `T` | Spline through points |
| `splineApprox` | `(points, tol=None, minDeg=1, maxDeg=3, smoothing=None, forConstruction=False, includeCurrent=False, makeWire=False)` | `T` | Spline approximation |
| `parametricCurve` | `(func, N=20, start=0, stop=1, tol=1e-3, minDeg=1, maxDeg=3, smoothing=None, makeWire=False)` | `T` | Spline from parametric function |
| `parametricSurface` | `(func, N=10, start=0, stop=1, tol=1e-3, minDeg=1, maxDeg=3, smoothing=None)` | `T` | Surface from parametric function |
| `bezier` | `(listOfXYTuple, forConstruction=False, includeCurrent=False, makeWire=False)` | `T` | Cubic Bezier curve |
| `threePointArc` | `(point1, point2, forConstruction=False)` | `T` | Arc through 3 points |
| `sagittaArc` | `(endPoint, sag, forConstruction=False)` | `T` | Arc defined by sagitta |
| `radiusArc` | `(endPoint, radius, forConstruction=False)` | `T` | Arc defined by radius |
| `tangentArcPoint` | `(endpoint, forConstruction=False, relative=True)` | `T` | Tangent arc to endpoint |
| `ellipseArc` | `(x_radius, y_radius, angle1=360, angle2=360, rotation_angle=0.0, sense=1, forConstruction=False, startAtCurrent=True, makeWire=False)` | `T` | Elliptical arc |
| `close` | `()` | `T` | Close wire |
| `mirrorX` | `()` | `T` | Mirror around X axis |
| `mirrorY` | `()` | `T` | Mirror around Y axis |

### 3D Operations
| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `extrude` | `(until=None, combine=True, clean=True, both=False, taper=None)` | `T` | Extrude pending wires into prismatic solid |
| `revolve` | `(angleDegrees=360, axisStart=None, axisEnd=None, combine=True, clean=True)` | `T` | Revolve pending wires around axis |
| `sweep` | `(path=None, multisection=False, sweepAlongWires=None, makeSolid=True, isFrenet=False, combine=True, clean=True, transition='right', normal=None, auxSpine=None)` | `T` | Sweep pending wires along path |
| `loft` | `(ruled=False, combine=True, clean=True)` | `T` | Loft through set of wires |
| `twistExtrude` | `(distance, angleDegrees, combine=True, clean=True)` | `T` | Extrude with twist |
| `interpPlate` | `(surf_edges=None, surf_pts=None, thickness=0, combine=True, clean=True, degree=3, nbPtsOnCur=15, nbIter=2, anisotropy=False, tol2d=1e-5, tol3d=1e-5, tolAng=1e-5, tolCurv=1e-5, maxDeg=8, maxSegments=9)` | `T` | Interpolated plate surface |
| `section` | `(height=0.0)` | `T` | Slice current solid at height |

### Boolean Operations
| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `union` | `(toUnion=None, clean=True, glue=False, tol=None)` | `T` | Union all stack items with current solid |
| `cut` | `(toCut=None, clean=True, tol=None)` | `T` | Subtract solid from current solid |
| `intersect` | `(toIntersect=None, clean=True, tol=None)` | `T` | Intersect with current solid |
| `combine` | `(clean=True, glue=False, tol=None)` | `T` | Combine all stack items into one |
| `split` | `(keepTop=False, keepBottom=False)` | `T` | Split solid into two parts |

### Holes
| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `hole` | `(diameter, depth=None, clean=True)` | `T` | Simple hole |
| `cboreHole` | `(diameter, cboreDiameter, cboreDepth, depth=None, clean=True)` | `T` | Counterbored hole |
| `cskHole` | `(diameter, cskDiameter, cskAngle, depth=None, clean=True)` | `T` | Countersunk hole |
| `cutEach` | `(fcn, useLocalCoords=False, clean=True)` | `T` | Evaluate function at each stack point |
| `cutBlind` | `(until=None, clean=True, both=False, taper=None)` | `T` | Prismatic cut to depth |
| `cutThruAll` | `(clean=True, taper=0)` | `T` | Prismatic cut through entire solid |

### Edge Treatments
| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `fillet` | `(radius)` | `T` | Fillet selected edges |
| `chamfer` | `(length, length2=None)` | `T` | Chamfer selected edges |
| `shell` | `(thickness, kind='arc')` | `T` | Shell (hollow) the solid, removing selected faces |

### Transforms
| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `rotate` | `(axisStartPoint, axisEndPoint, angleDegrees)` | `T` | Rotate around axis |
| `rotateAboutCenter` | `(axisEndPoint, angleDegrees)` | `T` | Rotate around center |
| `mirror` | `(mirrorPlane='XY', basePointVector=None, union=False)` | `T` | Mirror solid |
| `translate` | `(vec)` | `T` | Translate by vector |

### Arrays and Patterns
| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `rarray` | `(xSpacing, ySpacing, xCount, yCount, center=True)` | `T` | Rectangular array of points |
| `polarArray` | `(radius, startAngle, angle, count, fill=True, rotate=True)` | `T` | Polar array of points |
| `pushPoints` | `(pntList)` | `T` | Push list of points onto stack |

### Iteration
| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `each` | `(callback, useLocalCoordinates=False, combine=True, clean=True)` | `T` | Run function on each stack value |
| `eachpoint` | `(arg, useLocalCoordinates=False, combine=False, clean=True)` | `T` | Apply at each point position |

### Wire and Construction
| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `wire` | `(forConstruction=False)` | `T` | Connect pending edges into wire |
| `consolidateWires` | `()` | `T` | Consolidate wires into single |
| `toPending` | `()` | `T` | Add to pendingWires/pendingEdges |
| `offset2D` | `(d, kind='arc', forConstruction=False)` | `T` | 2D offset of wire |
| `largestDimension` | `()` | `float` | Largest dimension in stack |

### Sketching
| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `sketch` | `()` | `Sketch` | Initialize and return a Sketch |
| `placeSketch` | `(*sketches)` | `T` | Place sketches on current stack items |

### Export
| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `toSvg` | `(opts=None)` | `str` | Returns SVG text of first item |
| `exportSvg` | `(fileName)` | `None` | Export first item as SVG file |
| `export` | `(fname, tolerance=0.1, angularTolerance=0.1, opt=None)` | `T` | Export to file (STEP, STL, etc.) |
| `clean` | `()` | `T` | Remove unwanted edges from faces |

---

## Assembly Class (15 Public Methods)

| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `add` | `(obj, loc=None, name=None, color=None, material=None, metadata=None)` | `Self` | Add subassembly or object |
| `remove` | `(name: str)` | `Assembly` | Remove part/subassembly by name |
| `constrain` | `(q1, q2, kind, param=None)` | `Self` | Define binary constraint |
| `constrain` | `(q1, kind, param=None)` | `Self` | Define unary constraint |
| `solve` | `(verbosity=0)` | `Self` | Solve constraint system |
| `export` | `(path, exportType=None, mode='default', tolerance=0.1, angularTolerance=0.1, **kwargs)` | `Self` | Save to file |
| `save` | `(path, ...)` | `Self` | (Deprecated) Save to file |
| `importStep` | `(path)` | `Self` | Class method: read from STEP |
| `load` | `(path, importType=None)` | `Self` | Class method: load STEP/XBF/XML |
| `shapes` | `()` | `List[Shape]` | List of Shape objects |
| `traverse` | `()` | `Iterator` | Yield (name, child) pairs bottom-up |
| `toCompound` | `()` | `Compound` | Convert to Compound with locations |
| `addSubshape` | `(s, name=None, color=None, layer=None)` | `Assembly` | Add shape with metadata |

### Constraint Types for Assembly.constrain()
| Kind | Description | Example |
|------|-------------|---------|
| `"Plane"` | Faces are coplanar | `assy.constrain("a@faces@>Z", "b@faces@<Z", "Plane")` |
| `"Axis"` | Faces share common axis | `assy.constrain("a@faces@>X", "b@faces@>X", "Axis")` |
| `"Point"` | Points are coincident | `assy.constrain("a@vertices@>Z", "b@vertices@<Z", "Point")` |
| `"PointInPlane"` | Point lies in plane | `assy.constrain("a@vertices@>Z", "b@faces@>Z", "PointInPlane")` |

---

## Sketch Class (59 Public Methods)

### Face Construction
| Method | Signature | Description |
|--------|-----------|-------------|
| `face` | `(b, angle=0, mode='a', tag=None, ignore_selection=False)` | Construct face from wire/edges |
| `importDXF` | `(filename, tol=1e-6, exclude=[], include=[], angle=0, mode='a', tag=None)` | Import DXF |
| `rect` | `(w, h, angle=0, mode='a', tag=None)` | Rectangular face |
| `circle` | `(r, mode='a', tag=None)` | Circular face |
| `ellipse` | `(a1, a2, angle=0, mode='a', tag=None)` | Elliptical face |
| `trapezoid` | `(w, h, a1, a2=None, angle=0, mode='a', tag=None)` | Trapezoidal face |
| `slot` | `(w, h, angle=0, mode='a', tag=None)` | Slot-shaped face |
| `regularPolygon` | `(r, n, angle=0, mode='a', tag=None)` | Regular polygon face |
| `polygon` | `(pts, angle=0, mode='a', tag=None)` | Polygonal face from points |

### Location Distribution
| Method | Signature | Description |
|--------|-----------|-------------|
| `rarray` | `(xs, ys, nx, ny)` | Rectangular array of locations |
| `parray` | `(r, a1, da, n, rotate=True)` | Polar array of locations |
| `distribute` | `(n, start=0, stop=1, rotate=True)` | Distribute along edges/wires |
| `push` | `(locs, tag=None)` | Set selection to given locations |

### Modification
| Method | Signature | Description |
|--------|-----------|-------------|
| `each` | `(callback, mode='a', tag=None, ignore_selection=False)` | Apply callback on entities |
| `hull` | `(mode='a', tag=None)` | Convex hull from selection |
| `offset` | `(d, mode='a', tag=None)` | Offset wires/edges |
| `fillet` | `(d)` | Add fillet to selection |
| `chamfer` | `(d)` | Add chamfer to selection |
| `clean` | `()` | Remove internal wires |

### Selection
| Method | Signature | Description |
|--------|-----------|-------------|
| `tag` | `(tag)` | Tag current selection |
| `select` | `(*tags)` | Select by tags |
| `faces` | `(s=None, tag=None)` | Select faces |
| `wires` | `(s=None, tag=None)` | Select wires |
| `edges` | `(s=None, tag=None)` | Select edges |
| `vertices` | `(s=None, tag=None)` | Select vertices |
| `reset` | `()` | Reset selection |
| `delete` | `()` | Delete selected |

### Edge Construction
| Method | Signature | Description |
|--------|-----------|-------------|
| `edge` | `(val, tag=None, forConstruction=False)` | Add edge |
| `segment` | `(p1, p2, tag=None, forConstruction=False)` | Construct segment |
| `arc` | `(p1, p2, p3, tag=None, forConstruction=False)` | Construct arc |
| `spline` | `(pts, tangents=None, periodic=False, tag=None, forConstruction=False)` | Construct spline |
| `bezier` | `(pts, tag=None, forConstruction=False)` | Construct bezier |
| `close` | `(tag=None)` | Connect last to first edge |
| `assemble` | `(mode='a', tag=None)` | Assemble edges into faces |

### Constraints & Solving
| Method | Signature | Description |
|--------|-----------|-------------|
| `constrain` | `(tag, constraint, arg)` | Add constraint |
| `solve` | `()` | Solve constraints |

### Transforms
| Method | Signature | Description |
|--------|-----------|-------------|
| `copy` | `()` | Partial copy |
| `moved` | `(loc=None, x=0, y=0, z=0, rx=0, ry=0, rz=0)` | Copy with moved faces |
| `located` | `(loc)` | Copy with new location |

### Data Access
| Method | Signature | Description |
|--------|-----------|-------------|
| `finalize` | `()` | Finish and return parent |
| `val` | `()` | First selected item |
| `vals` | `()` | All selected items |

---

## Methods That DO NOT EXIST (Anti-Hallucination Guard)

These are methods LLMs commonly generate that are NOT part of CadQuery:

| Hallucinated Method | What It Sounds Like | What To Use Instead |
|---------------------|--------------------|--------------------|
| `.cone()` | Cone primitive | `Solid.makeCone(r1, r2, h)` or `.revolve()` a triangle |
| `.torus()` | Torus primitive | `Solid.makeTorus(r1, r2)` |
| `.helix()` | Helical path | `Wire.makeHelix(pitch, height, radius)` |
| `.thread()` / `.threadedHole()` | Screw thread | Manual via `.parametricCurve()` (see COOKBOOK.md Pattern 6) |
| `.offset3D()` | 3D offset | Use `.shell()` for offset solids |
| `.hole_pattern()` | Array of holes | `.pushPoints()` + `.hole()` |
| `.scale()` | Resize solid | Not supported: rebuild at new dimensions |
| `.extrudeToFace()` | Extrude until surface | Compute depth manually, use `.extrude(depth)` |
| `.compound_union()` | Union many at once | Loop `.union()` or `Compound.makeCompound()` |
| `.create_assembly()` | Auto-assembly | Use `cq.Assembly()` constructor + `.add()` |
| `.addComponent()` | Assembly add | Use `Assembly.add()` |
| `.mate()` | CadQuery Assembly mate | Only exists on `MAssembly` (cadquery-massembly) |
| `.snap()` | Snap features | No such thing: use constraints |

### Low-Level OCP Methods (Available but NOT on Workplane)
These are on `Solid`, `Face`, `Wire`, `Edge` etc., not on `Workplane`.
See `reference/cadquery_shape_primitives.md` for visual examples of each.

| Method | Class | Code Example | Usage |
|--------|-------|-------------|-------|
| `Solid.makeBox(l,w,h)` | `Solid` | `cq.Solid.makeBox(3,3,3)` | Direct box |
| `Solid.makeCylinder(r,h)` | `Solid` | `cq.Solid.makeCylinder(2,3)` | Direct cylinder |
| `Solid.makeCone(r1,r2,h)` | `Solid` | `cq.Solid.makeCone(3, 1, 3)` | Direct cone |
| `Solid.makeTorus(r1,r2)` | `Solid` | `cq.Solid.makeTorus(3, 1.5)` | Direct torus |
| `Solid.makeSphere(r)` | `Solid` | `cq.Solid.makeSphere(3, angleDegrees1=-90, angleDegrees2=90)` | Direct sphere |
| `Solid.makeSolid(shell)` | `Solid` | - | Solid from closed shell |
| `Face.makeRuledSurface(e1,e2)` | `Face` | - | Surface between two edges |
| `Shell.makeShell(faces)` | `Shell` | - | Shell from face list |
| `Wire.makeHelix(pitch,h,r)` | `Wire` | `cq.Wire.makeHelix(1, 4, 3)` | Helical wire |
| `Wire.makeCircle(r,center,normal)` | `Wire` | `cq.Wire.makeCircle(3, (0,0,0), (0,0,1))` | Circular wire |
| `Wire.makeEllipse(a,b,center,normal,dir)` | `Wire` | `cq.Wire.makeEllipse(3, 4, (0,0,0), (0,0,1), (1,0))` | Elliptical wire |
| `Edge.makeCircle(r)` | `Edge` | `cq.Edge.makeCircle(3)` | Circular edge |
| `Edge.makeEllipse(a,b)` | `Edge` | `cq.Edge.makeEllipse(3, 4)` | Elliptical edge |
| `Compound.makeCompound(solids)` | `Compound` | - | Combine without merging |
