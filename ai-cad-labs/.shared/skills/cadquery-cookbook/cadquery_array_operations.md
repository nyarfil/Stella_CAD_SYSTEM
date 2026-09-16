# CadQuery Array Operations
---

## pArray
[Workplane.polarArray](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.polarArray)

``` python
result = (
    cq.Workplane("XY")
    .polarArray(
        radius = 20,
        startAngle = 0,
        angle = 90,
        count = 20,
        fill = True,
        rotate = True
    )
    .box(1,1,1)
)
```

![02_parray_01](https://user-images.githubusercontent.com/19323166/273324012-743af2bb-06ed-4453-977a-079c4531343e.png)



## rarray

[Workplane.rarray](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.rarray)

``` python
result = (
    cq.Workplane("XY")
    .rarray(
        xSpacing = 10,
        ySpacing = 10,
        xCount = 5,
        yCount= 5,
        center = True)
    .box(1,1,1)
)
```

![rarray_01](https://user-images.githubusercontent.com/19323166/273321247-8509a6a8-a7c7-4939-b8a2-1b8b434e83e9.png)

---

## eachpoint example

[Workplane.eachpoint](https://cadquery.readthedocs.io/en/latest/classreference.html#cadquery.Workplane.eachpoint)


``` python
import cadquery as cq
from cadqueryhelper import shape

def add_star(loc):
    return shape.star().val().located(loc)

star_arc =(
    cq.Workplane("XY")
    .polarArray(
        radius  =150,
        startAngle  = 0,
        angle  = 90,
        count  = 15,
        fill = True,
        rotate = True
    )
    .eachpoint(add_star)
)
```

![03_parray_stars](https://user-images.githubusercontent.com/19323166/273329490-447b89a2-de36-409e-a59a-ec78c5e831a8.png)

---
