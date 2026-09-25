import unittest
import numpy as np
from ui.rain_simulation import Drop, RainSimulation, VISIBLE_RUNNERS, MAX_TRAILS
from ui.rain_surface import WetLayout, DROP_SCALE, separate_beads
from scipy.spatial import cKDTree


class RainTests(unittest.TestCase):
    def test_static_refill_cannot_steal_departed_runner_slots(self):
        sim = RainSimulation(600,500,23,pattern_scale=3.)
        for _ in range(VISIBLE_RUNNERS):
            sim.maintain_visible_flow()
        for _ in range(25):
            runners = [d for d in sim.drops if d.mobile]
            self.assertEqual(len(runners),VISIBLE_RUNNERS)
            # Keep this refill test independent of runner-to-runner merging.
            for index, drop in enumerate(runners):
                drop.x, drop.y = index*60., -100.
            runners[0].y = sim.height+100
            # A static spawn fires before the next flow replenishment.
            sim.flow_in = 1.
            sim.spawn_in = 0.
            sim.step(1/60)
            self.assertLessEqual(sum(not d.mobile for d in sim.drops),sim.target_count-VISIBLE_RUNNERS)
            sim.maintain_visible_flow()
            self.assertEqual(sum(d.mobile for d in sim.drops),VISIBLE_RUNNERS)
            self.assertLessEqual(len(sim.drops),sim.target_count)

    def test_runner_speed_difference_persists_after_release(self):
        sim = RainSimulation(600,500,23)
        slow = Drop(100,100,2,7,1,True,speed_factor=.55)
        fast = Drop(300,100,2,7,1,True,speed_factor=1.85)
        sim.drops = [slow,fast]
        sim.target_count = 0
        sim.rng.random = lambda: 0.
        sim.rng.uniform = lambda a,b: (a+b)/2
        for _ in range(120):
            sim.step(1/60)
        self.assertGreater(fast.y-100, (slow.y-100)*3)
        self.assertGreater(fast.target, slow.target*3)

    def test_initial_and_replacement_runners_enter_from_above_the_pane(self):
        sim = RainSimulation(1280,800,23,pattern_scale=3.)
        self.assertFalse(any(d.mobile for d in sim.drops))
        self.assertFalse(sim.trails)
        sim.maintain_visible_flow()
        top = sim.visible_bounds()[1]
        runners = [d for d in sim.drops if d.mobile]
        fixed = [d for d in sim.drops if not d.mobile]
        self.assertEqual(len(runners), 1)
        self.assertTrue(all(d.y+d.radius*DROP_SCALE*1.62 < top for d in runners))
        for drop in runners:
            drop.y = sim.height+40
        sim.flow_in = 0.
        sim.step(1/60)
        replacements = [d for d in sim.drops if d.mobile]
        self.assertEqual(len(replacements), 1)
        self.assertTrue(all(d.y+d.radius*DROP_SCALE*1.62 < top for d in replacements))
        self.assertTrue(all(not d.mobile for d in fixed))

    def test_spacing_keeps_microbeads_out_of_large_lenses(self):
        rng = np.random.default_rng(4)
        beads = np.zeros((40,10),np.float32)
        beads[:,:2] = rng.uniform(47,53,(40,2))
        beads[:,2:4] = .6
        beads[:,4] = 1
        obstacle = np.array([[50,50,10,10,1,0,0,0,1,0]],np.float32)
        separate_beads(beads,100,100,obstacle)
        self.assertGreater(np.linalg.norm(beads[:,:2]-50,axis=1).min(), 10)

    def test_visible_trails_finish_recovery_without_being_evicted(self):
        sim = RainSimulation(1280,800,23,pattern_scale=3.)
        for _ in range(3600):
            previous = {id(t):t for t in sim.trails}
            sim.step(1/30)
            remaining = {id(t) for t in sim.trails}
            self.assertFalse(any(t.life > 0 for key,t in previous.items() if key not in remaining))

    def test_spacing_reduces_overlaps_without_changing_population_or_sizes(self):
        beads = WetLayout(320,200,23).condensation
        beads[1,:2] = beads[0,:2]  # Exact coincident centers must separate safely.
        original = beads.copy()
        def overlaps(data):
            distances, neighbors = cKDTree(data[:,:2]).query(data[:,:2], k=8)
            radius = np.sqrt(data[:,2]*data[:,3])
            return np.count_nonzero(distances[:,1:] <
                .8*(radius[:,None]+radius[neighbors[:,1:]]))
        before = overlaps(beads)
        separate_beads(beads,320,200)
        self.assertTrue(np.isfinite(beads).all())
        self.assertLess(overlaps(beads), before*.25)
        np.testing.assert_array_equal(beads[:,2:],original[:,2:])
        self.assertEqual(beads.shape,original.shape)

    def test_repeated_collection_does_not_turn_a_runner_into_a_large_blob(self):
        sim = RainSimulation(1280,800,seed=8)
        runner = Drop(500,300,3.,7.,1.,True,4.,4.,10.)
        sim.drops = [runner]
        sim.target_count = 1
        for _ in range(30):
            small = Drop(runner.x,runner.y+.2,1.4,0.,1.)
            sim.drops.append(small)
            for _ in range(30):
                sim.step(1/60)
            self.assertNotIn(small,sim.drops)
        self.assertLessEqual(runner.radius, 3.*1.15)
        shape = list(sim.shapes())[-1]
        self.assertLess(shape[3], 3.*DROP_SCALE*1.7)

    def test_runners_arrive_individually_and_continue_after_departure(self):
        sim = RainSimulation(1280,800,23,pattern_scale=3.)
        births = []
        previous = set()
        for tick in range(2400):
            if tick == 1200:
                for drop in sim.drops:
                    if drop.mobile:
                        drop.y = sim.height+100
            sim.step(1/30)
            current = {id(d) for d in sim.drops if d.mobile}
            added = current-previous
            self.assertLessEqual(len(added),1)
            self.assertLessEqual(len(current),VISIBLE_RUNNERS)
            if added:
                births.append(sim.time)
            previous = current
        self.assertGreaterEqual(births[0],2.)
        self.assertTrue(all(b-a >= 1.99 for a,b in zip(births,births[1:])))
        self.assertTrue(any(t > 42 for t in births))
        self.assertTrue(sim.trails)

    def test_prepopulated_water_has_several_scales_and_monitor_variation(self):
        sim = RainSimulation(1707, 1067, seed=7)
        self.assertGreater(len(sim.drops), 500)
        self.assertGreater(len(sim.layout.condensation), 10000)
        sizes = np.array([d.radius for d in sim.drops])
        self.assertGreater(np.count_nonzero(sizes > 4), 150)
        self.assertLessEqual(sizes.max(), 3.5*sim.height/800)
        self.assertGreater(sizes.max()*DROP_SCALE/np.median(sim.layout.condensation[:,2]), 5)
        self.assertLess(sum(d.mobile for d in sim.drops)/len(sim.drops), .1)
        self.assertFalse(sim.trails)
        self.assertTrue(all(d.age > 1.5 for d in sim.drops))
        self.assertNotEqual(sim.drops[0].x, RainSimulation(1707, 1067, seed=8).drops[0].x)

    def test_condensation_has_wet_clusters_and_sparse_regions_in_zoomed_crop(self):
        for seed in (1, 7, 23):
            beads = WetLayout(1280, 800, seed).condensation
            for bounds in (((0,1280),(0,800)), ((1280/3,2560/3),(800/3,1600/3))):
                density, _, _ = np.histogram2d(beads[:,0], beads[:,1], bins=(8,5),
                                             range=bounds)
                self.assertGreater(density.min(), 0)
                self.assertGreater(density.max()/density.min(), 2.)
                self.assertGreater(density.std()/density.mean(), .20)
            self.assertGreater(np.std(beads[:,2]/beads[:,3]), .15)

    def test_old_rivulets_wander_and_vary_in_width(self):
        layout = WetLayout(1280, 800, seed=23)
        paths = {}
        for x0,y0,x1,y1,width,seed in layout.drainage_paths():
            paths.setdefault(seed, []).append((x0,y0,x1,y1,width))
        self.assertGreaterEqual(len(paths), 4)
        self.assertTrue(any(path[-1][3]-path[0][1] > 300 for path in paths.values()))
        for path in paths.values():
            self.assertGreater(np.ptp([p[2] for p in path]), 5)
            self.assertGreater(max(p[4] for p in path)/min(p[4] for p in path), 1.5)

    def test_same_size_exposure_preserves_wet_surface(self):
        sim = RainSimulation(800, 600, seed=3)
        layout = sim.layout
        trails = list(sim.trails)
        sim.resize(800, 600)
        self.assertIs(sim.layout, layout)
        self.assertEqual(sim.trails, trails)
        sim.resize(1000, 800)
        self.assertIsNot(sim.layout, layout)
        self.assertEqual((sim.layout.width,sim.layout.height), (1000,800))

    def test_pinned_beads_stay_and_runners_pause_and_release(self):
        sim = RainSimulation(1000, 800, seed=4)
        fixed = Drop(100, 100, 1.5, 5, 1)
        runner = Drop(500, 100, 7, 12, 1, True, 0, 0, .1)
        sim.drops = [fixed, runner]
        speeds = []
        for _ in range(1800):
            sim.step(1/60)
            speeds.append(runner.velocity)
        self.assertEqual((fixed.x, fixed.y), (100, 100))
        self.assertGreater(max(speeds), 10)
        self.assertTrue(any(a > 5 and b < a for a,b in zip(speeds, speeds[1:])))
        self.assertGreater(runner.y, 100)

    def test_collecting_bead_adds_volume_and_accelerates(self):
        sim = RainSimulation(600, 500, seed=3)
        runner = Drop(100, 100, 8, 0, 1, True, 4, 4, 10)
        small = Drop(103, 103, 2, 0, 1)
        sim.drops = [runner, small]
        sim.step(1/60)
        self.assertIn(small, sim.drops)
        self.assertTrue(small.absorbing)
        self.assertLess(runner.radius, (8**3 + 2**3)**(1/3))
        self.assertGreater(runner.target, 4)
        self.assertGreater(runner.merger, 0)
        for _ in range(30):
            sim.step(1/60)
        self.assertNotIn(small, sim.drops)
        self.assertAlmostEqual(runner.radius**3, 8**3 + 2**3, places=3)
        self.assertGreater(runner.deformation, .1)

    def test_absorbing_drop_stretches_toward_runner_during_collection(self):
        sim = RainSimulation(600, 500, seed=3)
        runner = Drop(100, 100, 5, 0, 1, True, 4, 4, 10)
        bead = Drop(100, 106, 2.5, 0, 1)
        sim.drops = [runner, bead]
        sim.step(1/60)
        self.assertTrue(bead.absorbing)
        shape = next(row for row in sim.shape_array() if row[6] == bead.seed)
        self.assertGreater(shape[3], shape[2])
        self.assertGreater(abs(shape[5]), .5)
        for _ in range(5):
            sim.step(1/60)
        self.assertGreater(bead.deformation, .3)
        shape = next(row for row in sim.shape_array() if row[6] == bead.seed)
        self.assertGreater(shape[3], shape[2])

    def test_runner_collects_contacted_drop_above_minimum_radius_regardless_of_size(self):
        sim = RainSimulation(600, 500, seed=3)
        runner = Drop(100, 100, 2, 0, 1, True, 4, 4, 10)
        larger_stationary = Drop(103, 103, 3, 0, 1)
        sim.drops = [runner, larger_stationary]
        sim.step(1/60)
        self.assertTrue(larger_stationary.absorbing)
        for _ in range(30):
            sim.step(1/60)
        self.assertNotIn(larger_stationary, sim.drops)
        self.assertLessEqual(runner.radius, runner.base_radius * 1.5 + 1e-6)

    def test_collecting_beads_caps_runner_at_one_and_a_half_times_base_radius(self):
        sim = RainSimulation(600, 500, seed=3)
        runner = Drop(100, 100, 8, 0, 1, True, 4, 4, 10)
        sim.drops = [runner]
        for _ in range(4):
            sim.drops.append(Drop(103, 103, 5, 0, 1))
            for _ in range(30):
                sim.step(1/60)
        self.assertLessEqual(runner.radius, 8 * 1.5 + 1e-6)

    def test_trails_expire_and_simulation_stays_bounded(self):
        sim = RainSimulation(1707, 1067, seed=5)
        sim.drops.clear()
        sim.target_count = 0
        for _ in range(2000):
            sim.step(.05)
        self.assertFalse(sim.trails)
        sim = RainSimulation(1707, 1067, seed=5)
        for _ in range(600):
            sim.step(.05)
        self.assertLessEqual(len(sim.drops), sim.target_count)
        self.assertLessEqual(len(sim.trails), MAX_TRAILS)

    def test_trail_recovery_takes_three_times_as_long(self):
        sim = RainSimulation(600, 500, seed=3)
        sim.drops.clear()
        sim.target_count = 0
        sim.add_trail(100, 100, 100, 120, 2, 0, life=18.)
        trail = sim.trails[0]
        for _ in range(360):
            sim.step(.05)
        self.assertIn(trail, sim.trails)
        self.assertAlmostEqual(trail.life, 12.)
        self.assertAlmostEqual(list(sim.shapes())[0][-1], 12.)
        for _ in range(721):
            sim.step(.05)
        self.assertFalse(sim.trails)

    def test_long_gap_does_not_teleport(self):
        sim = RainSimulation(600, 500, seed=3)
        runner = Drop(100, 100, 8, 0, 1, True, 30, 30, 10)
        sim.drops = [runner]
        sim.step(10)
        self.assertLess(runner.y-100, 2)


if __name__ == '__main__':
    unittest.main()
