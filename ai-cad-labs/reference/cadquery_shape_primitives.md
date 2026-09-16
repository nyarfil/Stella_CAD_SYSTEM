# CadQuery Shape primitives

---

# 3d shapes
## Box
[Workplane.box](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.box)
``` python
result = cq.Workplane("XY" ).box(3, 3, 3)
```
![07](https://user-images.githubusercontent.com/19323166/186888239-669bded2-6fa7-4ea9-86a4-9c6bcf061f77.png)

## Cone
[Solid.makeCone](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Solid.makeCone)
``` python
result = cq.Solid.makeCone(3, 1, 3)
```
![08](https://user-images.githubusercontent.com/19323166/186888251-ab4fd435-850f-4826-a5d5-5266b1fa06a4.png)


## Cylinder
[Workplane.cylinder](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.cylinder)
``` python
result = cq.Workplane("XY" ).cylinder(3, 2)
```
![09](https://user-images.githubusercontent.com/19323166/186888259-2ea568ed-4e8f-4e94-b4b0-8e337163dc57.png)

## Sphere
[Workplane.sphere](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.sphere)
``` python
result = cq.Workplane("XY" ).sphere(3)
```
[Solid.makeSphere](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Solid.makeSphere)
``` python
result = cq.Solid.makeSphere(3, angleDegrees1 = -90, angleDegrees2 =90, angleDegrees3 = 360)
```
![10](https://user-images.githubusercontent.com/19323166/186888272-d597d0a3-c8aa-4357-8acb-d0f22274687e.png)

## Text
[Workplane.text](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.text)
``` python
result = cq.Workplane("XY").text("Test",10, 2)
```
![11](https://user-images.githubusercontent.com/19323166/186888295-e4f5dccf-1299-40cb-a15c-702ca4c18772.png)

## Torus
[Solid.makeTorus](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Solid.makeTorus)
``` python
result = cq.Solid.makeTorus(3, 1.5)
```
![13](https://user-images.githubusercontent.com/19323166/186888323-adef2e6e-f431-4e7b-8c33-82cb12deba49.png)

## Wedge
[Workplane.wedge](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.wedge)
``` python
result = cq.Workplane("XY" ).wedge(3,3,3,1.5,1.5,1.5,1.5)
```
![12](https://user-images.githubusercontent.com/19323166/186888331-cd22c95f-1c2d-42cf-82ec-d0f75a8460c2.png)

---
# 2d Sketch shapes

## Arc
[Sketch.arc](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Sketch.arc)
``` python
result = cq.Sketch().arc((0,3), (1.5,1.5), (0,0))
```
![14](https://user-images.githubusercontent.com/19323166/186887922-59e7570b-1bb0-44ac-842e-9d3fc503f31b.png)

## Circle
[Sketch.circle](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Sketch.circle)
``` python
result = cq.Sketch().circle(4)
```
![15](https://user-images.githubusercontent.com/19323166/186887936-3c39c6ec-0528-4be3-88bf-333c2e0b053b.png)

## Ellipse
[Sketch.ellipse](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Sketch.ellipse)
``` python
result = cq.Sketch().ellipse(4,5)
```
![16](https://user-images.githubusercontent.com/19323166/186887946-f0a6ae0e-a5c0-4035-a6a3-16bd4e786984.png)

## Polygon
[Sketch.polygon](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Sketch.polygon)
``` python
pts = [(0,0),(0,4),(2,3) ,(4,4), (4,0)]
result = cq.Sketch().polygon(pts)
```
![17](https://user-images.githubusercontent.com/19323166/186887970-e80e1714-5202-4124-b003-b081d46523fc.png)

## Rect
[Sketch.rect](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Sketch.rect)
``` python
result = cq.Sketch().rect(4,4)
```
![18](https://user-images.githubusercontent.com/19323166/186887987-93189d0e-41b0-48a4-b056-799989cf2fbf.png)

## Regular Polygon
[Sketch.regularPolygon](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Sketch.regularPolygon)
``` python
result = cq.Sketch().regularPolygon(3,5)
```
![19](https://user-images.githubusercontent.com/19323166/186888001-4611ddc7-985d-4a8d-8dfa-279012338df5.png)

## Slot
[Sketch.slot](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Sketch.slot)
``` python
result = cq.Sketch().slot(1.5, 0.5, angle=90)
```
![20](https://user-images.githubusercontent.com/19323166/186888042-eb04d9f9-f12f-46ab-aee9-5ef102881ab9.png)

## Spline
[Sketch.spline](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Sketch.spline)
``` python
pts = [(0,0),(0,4),(2,3) ,(4,4)]
result = cq.Sketch().spline(pts)
```
![21](https://user-images.githubusercontent.com/19323166/186888057-92e03ee3-9325-47bb-bd69-176255bce623.png)

## Trapezoid
[Sketch.trapezoid](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Sketch.trapezoid)
``` python
result = cq.Sketch().trapezoid(4,3,70)
```
![22](https://user-images.githubusercontent.com/19323166/186888073-de5cd4e0-1c08-4762-b3fd-03a398ab1dc3.png)
---

# 2d shapes
[2d operations](https://cadquery.readthedocs.io/en/latest/apireference.html#d-operations)

## Circle
[Workplane.circle](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.circle)
``` python
result = cq.Workplane("XY" ).circle(3)
```
``` python
result = cq.Edge.makeCircle(3)
```
[Wire.makeCircle](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Wire.makeCircle)
``` python
result = cq.Wire.makeCircle(3, (0,0,0), (0,0,1))
```

![01](https://user-images.githubusercontent.com/19323166/186887498-16a15b7e-7b48-4543-9078-962b37ac8789.png)


## Ellipse
[Workplane.ellipse](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.ellipse)
``` python
result = cq.Workplane("XY" ).ellipse(3,4)
```
``` python
result = cq.Edge.makeEllipse(3,4)
```
[Wire.makeEllipse](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Wire.makeEllipse)
``` python
result = cq.Wire.makeEllipse(3, 4, (0,0,0),(0,0,1), (1,0))
```

![02](https://user-images.githubusercontent.com/19323166/186887562-815013f0-a192-48f4-9330-3e8df8163fad.png)

## Helix
[Wire.makeHelix](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Wire.makeHelix)
``` python
result = cq.Wire.makeHelix(1, 4, 3)
```

![03](https://user-images.githubusercontent.com/19323166/186887633-6ffa748c-a153-4a39-b2b1-6c0742a95ad4.png)

## Line
[Workplane.line](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.line)

``` python
result = cq.Workplane("XY" ).line(1,3)
```

![30](https://user-images.githubusercontent.com/19323166/186970869-d6563591-995e-4ecf-9c61-5ebdec6a8b7f.png)


## Line To
[Workplane.lineTo](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.lineTo)

![31](https://user-images.githubusercontent.com/19323166/186970899-bcc87eed-4065-45aa-89dd-6044ceb7c15a.png)

``` python
result = cq.Workplane("XY" ).lineTo(1,3)
```

## Rect
[Workplane.rect](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.rect)
``` python
result = cq.Workplane("XY" ).rect(3, 3)
```

![04](https://user-images.githubusercontent.com/19323166/186887653-b7ea5037-6d43-4603-8df0-e2308294b954.png)

## Polygon
[Workplane.polygon](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.polygon)
``` python
result = cq.Workplane("XY").polygon(6, 1)
```
![05](https://user-images.githubusercontent.com/19323166/186887669-89d1cbbc-adab-4578-be77-909e172a22c0.png)

## Polyline
[Workplane.polyline](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.polyline)
``` python
pts = [(0,0),(0,4),(2,3) ,(4,4), (4,0)]
result = cq.Workplane("XY").polyline(pts).close()
```
![06](https://user-images.githubusercontent.com/19323166/186887686-cae82397-4cc0-4e36-8f85-824ceb949bb5.png)

## slot2d
[Workplane.slot2D](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.slot2D)
``` python
result = cq.Workplane("XY").slot2D(5,2)
```
![39](https://user-images.githubusercontent.com/19323166/187073935-ed3b62ca-e7f1-463f-805a-3e6181b4cdf8.png)


## spline
[Workplane.spline](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.spline)
``` python
pts = [(0,0),(0,4),(2,5) ]
path = cq.Workplane("XY").spline(pts)
```
![25](https://user-images.githubusercontent.com/19323166/186887869-1f53778f-b8f2-407a-84db-cbec3883b9d2.png)

---

# operations


## Chamfer
[Workplane.chamfer](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.chamfer)

``` python
origin = cq.Workplane("XY").polygon(6, 20).extrude(10).translate((0,0,-1*(10/2)))
result = origin.chamfer(1,2)
```

![38](https://user-images.githubusercontent.com/19323166/187069380-3f00efd9-31cf-40c4-9be2-f57bda57fbef.png)

## Extrude
[Workplane.extrude](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.extrude)
``` python
result = cq.Workplane("XY" ).rect(3, 3).extrude(2)
```
![26](https://user-images.githubusercontent.com/19323166/186888409-3840eb02-2c02-4fca-addb-1502bf13ccec.png)

## Fillet
[Workplane.fillet](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.fillet)

[wikipedia](https://en.wikipedia.org/wiki/Fillet_(mechanics))
``` python
result = (
    cq.Workplane("XY")
    .box(10,10,10)
    .edges()
    .fillet(1)
)
```
![37](https://user-images.githubusercontent.com/19323166/187067048-40f3b465-a628-4c6d-828c-198d6f9c4645.png)

### Note
* Fillet has specific tolerances; if the fillet is too large the code will fail.

``` python
result = (
    cq.Workplane("XY")
    .box(10,10,10)
    .edges()
    .fillet(5)
)
```
![36](https://user-images.githubusercontent.com/19323166/187067043-b4dafe07-f531-4e3e-b3de-d17f8ffc355c.png)


## Hole
[Workplane.hole](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.hole)
``` python
result = cq.Workplane("XY").box(2,2,1).faces(">Z").hole(1,2)
```
![32](https://user-images.githubusercontent.com/19323166/187063948-265c5bd1-1947-426b-9e6f-42be0618f096.png)


## Loft
[Workplane.loft](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.loft)
``` python
result = (cq.Workplane("front").circle(1.5).workplane(offset=3.0).rect(0.75, 0.5).loft(combine=True))
```
![28](https://user-images.githubusercontent.com/19323166/186896038-4ba2a944-de47-4a6c-8fb8-133a83c89fec.png)

## Rotate
[Workplane.rotate](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.rotate)
``` python
result = cq.Workplane("XY" ).box(3, 3, 2).rotate((0,0,1), (0,0,0), 30)
```
![27](https://user-images.githubusercontent.com/19323166/186888468-1b3ba5e9-a93b-4168-8498-5ab8253dbfd0.png)

## Shell
[Workplane.shell](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.shell)

### Negative shell
``` python
result = cq.Workplane().box(10, 10, 10).faces("+Z").shell(-1)
```

![40](https://user-images.githubusercontent.com/19323166/213916431-51defbcc-1446-4ad9-a0a0-be54e7d76e3f.png)

### Positiv Shell

``` python
result = cq.Workplane().box(10, 10, 10).faces("+Z").shell(-1)
```

![41](https://user-images.githubusercontent.com/19323166/213916519-9ca1c989-d7ae-427c-8039-7556bba89a5f.png)


## Sweep
[Workplane.sweep](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.sweep)
``` python
pts = [(0,0),(0,4),(2,5) ]
path = cq.Workplane("XZ").spline(pts)
rect = cq.Workplane("XY" ).rect(3, 3)
result = rect.sweep(path)
```
![24](https://user-images.githubusercontent.com/19323166/186888448-2353e1f6-e537-4cd9-930b-50880431761b.png)

## Translate
[Workplane.translate](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.translate)
``` python
rect = cq.Workplane("XY" ).box(3, 3, 2).translate((5,5,1))
```
![29](https://user-images.githubusercontent.com/19323166/186896744-347bd806-8def-43c1-9fc6-0afe89302cd6.png)

## TwistExtrude
[Workplane.twistExtrude](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.twistExtrude)
``` python
result = cq.Workplane("XY" ).rect(3, 3).twistExtrude(2,45)
```
![23](https://user-images.githubusercontent.com/19323166/186888435-aa899bf2-ddae-40ef-acf9-2fc7edbe1dd8.png)

---

# Plugins

## CboreHole
[Workplane.cboreHole](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.cboreHole)

``` python
result = (
    cq.Workplane("XY")
    .box(10,10,5)
    .faces(">Z")
    .cboreHole(2,4,1.5)
)
```
![33](https://user-images.githubusercontent.com/19323166/187064610-de7b2d40-c0fe-4529-aee7-d235f2ff1906.png)


## CskHole
[Workplane.cskHole](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.cskHole)

``` python
result = (
    cq.Workplane("XY")
    .box(10,10,5)
    .faces(">Z")
    .cskHole(2, 4, 82, depth=None)
)
```
![35](https://user-images.githubusercontent.com/19323166/187065236-f07ed9aa-c53a-44d7-af34-10242f069564.png)
