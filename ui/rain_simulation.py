"""Attached water, viscous runners and drainage history in logical pixels."""
from dataclasses import dataclass
import math
import random
import numpy as np
from scipy.spatial import cKDTree
from ui.rain_surface import WetLayout, DROP_SCALE, separate_beads

VISIBLE_RUNNERS = 8
TRAIL_RECOVERY_TIME_SCALE = 3.
MAX_TRAILS = 7800

@dataclass(slots=True)
class Drop:
    x: float
    y: float
    radius: float
    seed: float
    aspect: float
    mobile: bool = False
    velocity: float = 0.
    target: float = 0.
    hold: float = 0.
    age: float = 10.
    trail_x: float = 0.
    trail_y: float = 0.
    deformation: float = 0.
    merger: float = 0.
    rest_radius: float = 0.
    lateral_slope: float = 0.
    lateral_target: float = 0.
    steer_in: float = 0.
    speed_factor: float = 1.
    material_strength: float = 0.
    base_radius: float = 0.
    absorbing: bool = False
    absorb_target: object = None
    absorb_elapsed: float = 0.
    absorb_duration: float = .32
    absorb_start_x: float = 0.
    absorb_start_y: float = 0.
    absorb_start_radius: float = 0.
    absorb_volume: float = 0.
    absorb_applied: float = 0.

    def __post_init__(self):
        self.rest_radius = self.radius
        self.base_radius = self.radius
        if self.material_strength == 0.:
            self.material_strength = .82 + .24*((self.seed*.61803398875) % 1.)


@dataclass(slots=True)
class Trail:
    x: float
    y: float
    width: float
    length: float
    angle: float
    life: float
    seed: float


class RainSimulation:
    def __init__(self, width, height, seed=None, pattern_scale=1.):
        self.rng = random.Random(seed)
        self.pattern_scale = pattern_scale
        self.flow_in = self.rng.uniform(2.,3.)
        self.width, self.height = max(1, width), max(1, height)
        self.time = 0.
        self.drops = []
        self.trails = []
        self._shape_buffer = np.empty((0, 10), dtype=np.float32)
        self.layout = WetLayout(self.width, self.height, self.rng.randrange(2**32))
        self.static_revision = 0
        self.target_count = max(30, min(975, int(width * height / 1800)))
        self.spawn_positions = list(self.layout.positions(self.target_count+32))
        self._static_count = 0
        static_count = self.target_count - (VISIBLE_RUNNERS if self.pattern_scale > 1 else 0)
        occupied = np.empty((static_count, 3), dtype=np.float64)
        for index in range(static_count):
            drop = self.new_drop(initial=True, occupied=occupied[:index])
            self.drops.append(drop)
            occupied[index] = drop.x, drop.y, drop.radius*max(drop.aspect, 1.05)
        self.space_static_drops()
        self._static_count = sum(not drop.mobile for drop in self.drops)
        self.space_condensation()
        self.spawn_in = self.rng.expovariate(2.)

    def visible_bounds(self):
        half_w, half_h = self.width/(2*self.pattern_scale), self.height/(2*self.pattern_scale)
        return (self.width/2-half_w, self.height/2-half_h,
                self.width/2+half_w, self.height/2+half_h)

    def maintain_visible_flow(self):
        # Zoom crops most of the simulation away. Keep a few independent
        # runners inside the actual pane, not merely somewhere off screen.
        if self.pattern_scale <= 1 or self.target_count == 0:
            return
        left, top, right, bottom = self.visible_bounds()
        # Count queued drops above the pane too. Never turn a bead already
        # visible on the glass into a newly initialized falling drop.
        count = sum(d.mobile and d.y < bottom+d.radius*DROP_SCALE*2 for d in self.drops)
        for _ in range(min(1, max(0, VISIBLE_RUNNERS-count), self.target_count-len(self.drops))):
            radius = self.rng.uniform(1.8,3.)*self.height/800
            x = self.rng.uniform(left+(right-left)*.04, right-(right-left)*.04)
            y = top-radius*DROP_SCALE*self.rng.uniform(2.,3.)
            speed_factor = self.rng.uniform(.55,1.85)
            velocity = self.rng.uniform(4.,8.)*speed_factor
            self.drops.append(Drop(x,y,radius,self.rng.uniform(0,100),self.rng.uniform(.7,1.1),
                                   True,velocity,velocity,self.rng.uniform(1.,3.),
                                   trail_x=x,trail_y=y,speed_factor=speed_factor))

    def new_drop(self, initial=False, occupied=None):
        rng = self.rng
        size = rng.random()
        scale = self.height/800
        radius = (rng.uniform(1.2, 2.6) if size < .46 else
                  rng.uniform(2.8, 3.5)) * scale
        # Keep the same population and size distribution, but reject crowded
        # spawn positions instead of stacking another bead on an existing one.
        best = None
        clearance = -float('inf')
        # Positions stay fixed throughout this spawn search. Evaluate all
        # clearances in NumPy instead of revisiting Python objects per attempt.
        if occupied is None:
            occupied = np.asarray([(d.x, d.y, d.radius*max(d.aspect, 1.05))
                                   for d in self.drops], dtype=np.float64).reshape(-1, 3)
        for _ in range(24):
            if not self.spawn_positions:
                self.spawn_positions = list(self.layout.positions(64))
            x, y = self.spawn_positions.pop()
            gap = float(np.min(np.hypot(x-occupied[:, 0], y-occupied[:, 1]) -
                               (radius*1.25+occupied[:, 2])*DROP_SCALE*1.1,
                               initial=float('inf')))
            if not initial:
                # Later replacement beads also prefer gaps in the baked
                # condensation, without rebaking or moving that texture.
                beads = self.layout.condensation
                # Ordinary overlap clearance, independent of droplet size class.
                halo = radius*DROP_SCALE*1.15
                near = self.condensation_tree.query_ball_point((x,y),halo+5)
                if near:
                    nearby = beads[near]
                    micro_gap = np.linalg.norm(nearby[:,:2]-(x,y),axis=1) - (
                        halo+np.sqrt(nearby[:,2]*nearby[:,3]))
                    gap = min(gap,float(micro_gap.min()))
            if gap > clearance:
                best, clearance = (x,y), gap
            if gap >= 0:
                break
        x, y = best
        return Drop(x, y, radius, rng.uniform(0, 100), rng.uniform(.58, 1.20),
                    age=10. if initial else 0., trail_x=x, trail_y=y)

    def space_static_drops(self):
        fixed = [d for d in self.drops if not d.mobile]
        shapes = np.asarray([(d.x,d.y,d.radius*DROP_SCALE*d.aspect,
                              d.radius*DROP_SCALE*1.05,1.,0.,d.seed,0.,1.,0.)
                             for d in fixed], np.float32).reshape(-1,10)
        separate_beads(shapes, self.width, self.height)
        for drop, shape in zip(fixed, shapes):
            drop.x, drop.y = float(shape[0]), float(shape[1])
            drop.trail_x, drop.trail_y = drop.x, drop.y

    def space_condensation(self):
        # The 3x skin only displays the center crop. Include a margin for edge
        # lenses, but don't spend cover-start time spacing invisible geometry.
        left, top, right, bottom = self.visible_bounds()
        margin = 20*self.height/800
        beads = self.layout.condensation
        visible = ((beads[:,0] >= left-margin) & (beads[:,0] <= right+margin) &
                   (beads[:,1] >= top-margin) & (beads[:,1] <= bottom+margin))
        selected = beads[visible].copy()
        obstacles = np.asarray([
            (d.x,d.y,d.radius*DROP_SCALE*d.aspect,d.radius*DROP_SCALE*1.05,
             1.,0.,d.seed,0.,1.,0.) for d in self.drops
            if left-margin <= d.x <= right+margin and top-margin <= d.y <= bottom+margin
        ], dtype=np.float32).reshape(-1,10)
        separate_beads(selected, self.width, self.height, obstacles)
        beads[visible] = selected
        self.condensation_tree = cKDTree(self.layout.condensation[:,:2].copy())

    def resize(self, width, height):
        width, height = max(1, width), max(1, height)
        if (width,height) == (self.width,self.height):
            return
        for drop in self.drops:
            drop.x *= width / self.width
            drop.y *= height / self.height
            drop.trail_x, drop.trail_y = drop.x, drop.y
        self.trails.clear()
        self.width, self.height = width, height
        self.layout = WetLayout(width, height, self.rng.randrange(2**32))
        self.space_static_drops()
        self.space_condensation()
        self.spawn_positions.clear()
        self.static_revision += 1
        self.flow_in = self.rng.uniform(2.,3.)
        self.target_count = max(30, min(975, int(width * height / 1800)))

    def add_trail(self, x0, y0, x1, y1, radius, seed, life=35., width_ratio=.40):
        length = math.hypot(x1-x0, y1-y0)
        if length < .01:
            return
        if self.pattern_scale > 1:
            # Offscreen drainage cannot affect the cropped pane; resize clears
            # this history anyway. Keep room for visible paths to finish fading.
            left, top, right, bottom = self.visible_bounds()
            margin = radius*DROP_SCALE*1.8 + length*.2
            if (max(x0,x1)+margin < left or min(x0,x1)-margin > right or
                    max(y0,y1)+margin < top or min(y0,y1)-margin > bottom):
                return
        # Overlapping height segments form one continuous lens in the shader.
        self.trails.append(Trail((x0+x1)/2, (y0+y1)/2, max(.15, radius*width_ratio),
                                 length/2, -math.atan2(x1-x0, y1-y0), life, seed))

    def step(self, dt):
        dt = min(max(dt, 0.), .05)  # Don't jump across the screen after a UI stall.
        self.time += dt
        for trail in self.trails:
            trail.life -= dt / TRAIL_RECOVERY_TIME_SCALE
        # Compact the existing list in place. This path runs on every animation
        # tick; rebuilding it twice per frame creates avoidable short-lived
        # lists and puts pressure on Python's allocator without changing the
        # order or lifetime of any visible trail.
        write = 0
        for trail in self.trails:
            if trail.life > 0:
                self.trails[write] = trail
                write += 1
        if write != len(self.trails):
            del self.trails[write:]
        if len(self.trails) > MAX_TRAILS:
            del self.trails[:-MAX_TRAILS]
        cells = {}
        active_absorb_volume = {}
        for index, drop in enumerate(self.drops):
            cells.setdefault((int(drop.x//32), int(drop.y//32)), []).append(index)
            if drop.absorbing and drop.absorb_target is not None:
                target_key = id(drop.absorb_target)
                active_absorb_volume[target_key] = (
                    active_absorb_volume.get(target_key, 0.) +
                    drop.absorb_volume - drop.absorb_applied)
        consumed = set()
        merger_decay = math.exp(-dt*1.5)
        deformation_blend = 1-math.exp(-dt*4)
        velocity_blend = 1-math.exp(-dt*2.8)
        lateral_blend = 1-math.exp(-dt*1.3)
        bottom = self.visible_bounds()[3]
        for index, drop in enumerate(self.drops):
            if index in consumed:
                continue
            drop.age += dt
            if drop.absorbing:
                target = drop.absorb_target
                if target is None or target not in self.drops:
                    consumed.add(index)
                    continue
                drop.absorb_elapsed += dt
                progress = min(1., drop.absorb_elapsed / drop.absorb_duration)
                eased = progress * progress * (3. - 2. * progress)
                desired = drop.absorb_volume * eased
                delta = max(0., desired - drop.absorb_applied)
                if delta:
                    target.radius = min(target.base_radius * 1.5,
                                        max(target.radius, (target.radius**3 + delta)**(1/3)))
                    drop.absorb_applied += delta
                drop.x = drop.absorb_start_x + (target.x - drop.absorb_start_x) * eased
                drop.y = drop.absorb_start_y + (target.y - drop.absorb_start_y) * eased
                drop.radius = max(.05, drop.rest_radius * (1. - eased))
                drop.deformation = min(.9, .18 + .62 * math.sin(math.pi * progress))
                if progress >= 1.:
                    consumed.add(index)
                continue
            # Pinned beads normally have no deformation to integrate. Keep
            # aging them for fade-in, and still settle any nonzero motion.
            if not drop.mobile and drop.velocity == 0. and drop.merger == 0. and drop.deformation == 0.:
                continue
            drop.merger *= merger_decay
            stretch = min(.30, drop.velocity*.015) + drop.merger*.06
            drop.deformation += (stretch-drop.deformation)*deformation_blend
            if not drop.mobile:
                continue
            drop.hold -= dt
            if drop.hold <= 0:
                release = self.rng.random() < (.78 if drop.radius > 6 else .60)
                drop.target = (self.rng.uniform(.6, 1.4) * max(5.,drop.radius**1.5*.9)*drop.speed_factor if release
                               else self.rng.uniform(0, .35))
                drop.hold = self.rng.uniform(.5, 2.6) if release else self.rng.uniform(.8, 3.5)
            irregular = 1 + .20 * math.sin(self.time*2.1 + drop.seed)
            drop.velocity += (drop.target*irregular - drop.velocity) * velocity_blend
            drop.steer_in -= dt
            if drop.steer_in <= 0:
                drop.lateral_target = self.rng.uniform(-.045,.045)
                drop.steer_in = self.rng.uniform(3.,7.)
            drop.lateral_slope += (drop.lateral_target-drop.lateral_slope)*lateral_blend
            drop.y += drop.velocity * dt
            drop.x += drop.lateral_slope * drop.velocity * dt
            if math.hypot(drop.x-drop.trail_x, drop.y-drop.trail_y) > 1.6:
                self.add_trail(drop.trail_x, drop.trail_y, drop.x, drop.y, drop.radius,
                               drop.seed, life=18., width_ratio=.90)
                drop.trail_x, drop.trail_y = drop.x, drop.y
            if drop.velocity > 1:
                cx, cy = int(drop.x//32), int(drop.y//32)
                reach = math.ceil((drop.radius+22.)*.85*DROP_SCALE/32)
                for dx in range(-reach, reach+1):
                    for dy in range(-reach, reach+1):
                        for other_index in cells.get((cx+dx, cy+dy), ()):
                            if other_index == index or other_index in consumed:
                                continue
                            other = self.drops[other_index]
                            # Any contacted stationary drop above the minimum
                            # radius participates, even when it is larger than
                            # the falling runner. The runner growth cap below
                            # still limits how much volume can be collected.
                            if other.absorbing:
                                continue
                            if math.hypot(other.x-drop.x, other.y-drop.y) < (drop.radius+other.radius)*.85*DROP_SCALE:
                                # Keep the struck lens alive briefly so it can
                                # stretch into the runner instead of vanishing.
                                max_volume = max(0., (drop.base_radius*1.15)**3 - drop.radius**3)
                                reserved = active_absorb_volume.get(id(drop), 0.)
                                volume = min(other.radius**3, max(0., max_volume - reserved))
                                if volume <= .001:
                                    consumed.add(other_index)
                                    continue
                                    continue
                                other.absorbing = True
                                other.absorb_target = drop
                                other.absorb_elapsed = 0.
                                other.absorb_start_x, other.absorb_start_y = other.x, other.y
                                other.absorb_start_radius = other.radius
                                other.absorb_volume = volume
                                other.absorb_applied = 0.
                                other.absorb_duration = self.rng.uniform(.26, .38)
                                drop.target = max(drop.target, drop.radius**1.5*1.1*drop.speed_factor)
                                drop.hold = self.rng.uniform(.4, 1.2)
                                drop.merger = min(1.5, drop.merger + .65)
            if drop.y > bottom + drop.radius*DROP_SCALE*2:
                consumed.add(index)
        if consumed:
            removed_static = sum(not self.drops[index].mobile for index in consumed)
            self.drops = [drop for index, drop in enumerate(self.drops) if index not in consumed]
            self._static_count -= removed_static
        self.flow_in -= dt
        if self.flow_in <= 0:
            self.flow_in = self.rng.uniform(2.,4.)
            self.maintain_visible_flow()
        self.spawn_in -= dt
        if self.spawn_in <= 0:
            self.spawn_in = self.rng.expovariate(2.)
            # Static condensation must not take a departed runner's slot
            # while flow replenishment is waiting for its next tick.
            static_limit = self.target_count - (VISIBLE_RUNNERS if self.pattern_scale > 1 else 0)
            if len(self.drops) < self.target_count and self._static_count < static_limit:
                self.drops.append(self.new_drop())
                self._static_count += 1

    def shapes(self):
        """center, radii, rotation, seed, kind, opacity, motion for one GPU batch."""
        for trail in self.trails:
            width = trail.width*DROP_SCALE
            yield (trail.x, trail.y, width, trail.length+width,
                   math.cos(trail.angle), math.sin(trail.angle), trail.seed, 1.,
                   min(1., trail.life/25.), trail.life)
        for drop in self.drops:
            if drop.absorbing:
                opacity = min(1., drop.age/1.5) * drop.material_strength * (1. - min(1., drop.absorb_elapsed/drop.absorb_duration))
                target = drop.absorb_target
                angle = math.atan2(target.y-drop.y, target.x-drop.x) if target else 0.
                stretch = drop.deformation
                yield (drop.x, drop.y,
                       drop.radius*DROP_SCALE*drop.aspect/(1.+stretch),
                       drop.radius*DROP_SCALE*(1.05+stretch),
                       math.cos(angle), math.sin(angle), drop.seed, 0., opacity,
                       stretch)
                continue
            stretch = drop.deformation
            relative_size = drop.radius*800/self.height
            size_strength = .70+.30*min(1.,max(0.,(relative_size-1.2)/2.3))
            merge_shape = min(.20, drop.merger*.12) if drop.mobile else 0.
            yield (drop.x, drop.y, drop.radius*DROP_SCALE*drop.aspect/(1+stretch-merge_shape),
                   drop.radius*DROP_SCALE*(1.05+stretch+merge_shape), 1., 0., drop.seed, 0. if drop.mobile else -1.,
                   min(1., drop.age/1.5)*drop.material_strength*size_strength,
                   stretch+drop.merger)

    def shape_array(self):
        """Return the current GPU shape batch without per-frame list churn."""
        count = len(self.trails) + len(self.drops)
        if len(self._shape_buffer) < count:
            self._shape_buffer = np.empty((count + 128, 10), dtype=np.float32)
        shapes = self._shape_buffer[:count]
        index = 0
        for trail in self.trails:
            width = trail.width*DROP_SCALE
            shapes[index] = (trail.x, trail.y, width, trail.length+width,
                             math.cos(trail.angle), math.sin(trail.angle),
                             trail.seed, 1., min(1., trail.life/25.), trail.life)
            index += 1
        for drop in self.drops:
            if drop.absorbing:
                opacity = (min(1., drop.age/1.5) * drop.material_strength *
                           (1. - min(1., drop.absorb_elapsed/drop.absorb_duration)))
                target = drop.absorb_target
                angle = math.atan2(target.y-drop.y, target.x-drop.x) if target else 0.
                stretch = drop.deformation
                shapes[index] = (drop.x, drop.y,
                                 drop.radius*DROP_SCALE*drop.aspect/(1.+stretch),
                                 drop.radius*DROP_SCALE*(1.05+stretch),
                                 math.cos(angle), math.sin(angle), drop.seed,
                                 0., opacity, stretch)
                index += 1
                continue
            stretch = drop.deformation
            relative_size = drop.radius*800/self.height
            size_strength = .70+.30*min(1.,max(0.,(relative_size-1.2)/2.3))
            merge_shape = min(.20, drop.merger*.12) if drop.mobile else 0.
            shapes[index] = (drop.x, drop.y,
                             drop.radius*DROP_SCALE*drop.aspect/(1+stretch-merge_shape),
                             drop.radius*DROP_SCALE*(1.05+stretch+merge_shape), 1., 0.,
                             drop.seed, 0. if drop.mobile else -1.,
                             min(1., drop.age/1.5)*drop.material_strength*size_strength,
                             stretch+drop.merger)
            index += 1
        return shapes











