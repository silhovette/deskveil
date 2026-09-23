"""Water lenses sample ONLY GlassCompositor's finished, tinted surface texture."""

VERTEX = """
#version 120
attribute vec4 cornerCenter;
attribute vec4 radiiRotation;
attribute vec4 style;
uniform vec2 viewport;
uniform vec2 surfaceScale;
uniform int backdrop;
uniform float patternScale;
varying vec2 local;
varying vec2 uv;
varying vec2 pane;
varying vec2 radii;
varying vec4 material;
void main() {
    local = cornerCenter.xy;
    vec2 point = local * radiiRotation.xy;
    point = mat2(radiiRotation.z, radiiRotation.w,
                -radiiRotation.w, radiiRotation.z) * point + cornerCenter.zw;
    if (backdrop == 1) point = (local * .5 + .5) * viewport;
    else point = (point - viewport * .5) * patternScale + viewport * .5;
    vec2 screenPoint = point / viewport;
    pane = screenPoint;
    uv = screenPoint * surfaceScale;
    radii = radiiRotation.xy * patternScale;
    material = style;
    gl_Position = vec4(screenPoint.x * 2. - 1., 1. - screenPoint.y * 2., 0., 1.);
}
"""

HEIGHT_FRAGMENT = """
#version 120
varying vec2 local;
varying vec2 radii;
varying vec4 material;
varying vec2 pane;
void main() {
    float seed = material.x;
    if (material.y > .5) {
        // Rounded, overlapping capsules avoid rectangular ends and hard joins.
        float end = max(0.,abs(local.y)*radii.y-(radii.y-radii.x));
        float x = length(vec2(local.x,end/radii.x));
        // Different parts of a wiped path re-fog at different rates. The
        // pattern is fixed on the pane, so recovery never flickers or crawls.
        float patch = .5 + .5*sin(pane.x*53.+sin(pane.y*37.))*cos(pane.y*41.-pane.x*17.);
        float recovery = smoothstep(0.,mix(8.,14.,patch),material.w);
        float cleared = (1.-smoothstep(.65,1.15,x))*recovery;
        // A thicker irregular central thread within a wiped condensation path.
        // Adjacent segments add in height space, not as overlapping highlights.
        float height = pow(max(0.,1.-x*x*4.), .7)*radii.x*.32*material.z;
        gl_FragColor = vec4(height, cleared, 0., 0.);
        return;
    }
    vec2 p = local;
    float variation = fract(seed*.61803398875);
    float large = smoothstep(7.,14.,min(radii.x,radii.y));
    float neck = 1. + (.16+.10*variation)*p.y -
                 (.10+.08*variation)*material.w*max(0.,-p.y);
    p.x = (p.x + (.09+.07*variation+.06*large)*
           sin(p.y*(2.35+variation)+seed)*(1.-p.y*p.y))/neck;
    float angle = atan(p.y,p.x);
    // Larger lenses carry low-frequency asymmetry and stronger lobes, like
    // water left after several beads have merged rather than a molded ellipse.
    float outline = .91 + (.07+.055*variation)*sin(angle*2.+seed)
                    + (.025+.04*large)*sin(angle*3.-seed*1.7)
                    + large*(.055*sin(angle+seed*.37)
                             +.03*sin(angle*5.+seed*.83));
    float r = length(p)/outline;
    if (r >= 1.) discard;
    float cap = pow(max(0.,1.-r*r), .62);
    float height = cap * min(radii.x,radii.y) * .62 * material.z;
    // One coherent lens when neighboring lobes touch or droplets merge.
    if (material.y < -.5) {
        // Pinned water is masked only after all swept paths have combined.
        gl_FragColor = vec4(0., 0., 0., height);
    } else {
        float cleared = 1.-smoothstep(.80,1.,r);
        gl_FragColor = vec4(height, cleared, cap*material.z, 0.);
    }
}
"""

FRAGMENT = """
#version 120
uniform sampler2D frosted;
uniform sampler2D condensation;
uniform sampler2D flowing;
uniform vec2 viewport;
uniform vec2 surfaceScale;
uniform vec2 fieldTexel;
uniform float pixelRatio;
uniform int waterEnabled;
varying vec2 uv;
varying vec2 pane;
varying vec2 radii;

float waterHeight(vec2 p) {
    vec2 f = vec2(p.x, 1.-p.y);
    vec4 motion = texture2D(flowing,f);
    float beads = texture2D(condensation,f).r + motion.a;
    return beads * (1.-clamp(motion.g,0.,1.)) + motion.r;
}

void main() {
    vec3 base = texture2D(frosted,uv).rgb;
    if (waterEnabled == 0) { gl_FragColor=vec4(base,1.); return; }
    // Tint only the Rain skin, including its refracted privacy-safe image.
    base *= .85;
    vec3 film = texture2D(flowing,vec2(pane.x,1.-pane.y)).rgb;
    // White film sits above acrylic and below the water lenses. 98%
    // transparency means 2% opacity; swept areas expose the acrylic again.
    float mist = .02*(1.-clamp(film.g,0.,1.));
    base = mix(base,vec3(1.),mist);
    float h = waterHeight(pane);
    // Below the existing contact threshold the final mix is exactly base.
    // Skip neighbor samples, refraction and lighting for these dry pixels.
    if (h <= .014) { gl_FragColor = vec4(base,1.); return; }
    float right = waterHeight(pane+vec2(fieldTexel.x,0.));
    float left = waterHeight(pane-vec2(fieldTexel.x,0.));
    float down = waterHeight(pane+vec2(0.,fieldTexel.y));
    float up = waterHeight(pane-vec2(0.,fieldTexel.y));
    vec3 n = normalize(vec3((left-right)*pixelRatio*1.15,
                            (up-down)*pixelRatio*1.15, 1.));
    float contact = smoothstep(.010,.075,h);
    // Only the final privacy-safe image is bound here. Film height and normals
    // change refraction, never blur strength or access to the original desktop.
    vec2 displacement = n.xy*(4.+min(h,8.)*7.)/viewport*surfaceScale;
    vec3 lens = texture2D(frosted,clamp(uv+displacement,vec2(0.),vec2(1.))).rgb * .85;
    lens = mix(lens,vec3(1.),mist);
    vec3 light = normalize(vec3(-.38,-.54,.75));
    float facing = max(0.,dot(n,light));
    float softbox = pow(facing,14.);
    float side = pow(max(0.,dot(n,normalize(vec3(-.60,-.12,.79)))),24.);
    float shoulder = pow(facing,7.);
    float meniscus = (1.-n.z)*max(0.,dot(n.xy,normalize(vec2(-.48,-.68))));
    float shade = .78 + .22*n.z - max(0.,n.y)*.12;
    // Remove the trail's thin specular line; retain highlights on water drops.
    float trail = smoothstep(.02,.15,film.g)*(1.-smoothstep(.01,.08,film.b));
    float highlight = 1.-trail;
    // Small droplets have a shallower, softer glint; larger lenses catch more
    // of the softbox.  radii are the rendered screen-space half-extents.
    float dropRadius = min(radii.x,radii.y);
    float sizeHighlight = dropRadius <= 4.5 ? .20 : mix(.60,1.25,smoothstep(4.5,14.,dropRadius));
    vec3 body = mix(base,lens*shade,contact);
    vec3 specular = highlight*sizeHighlight*1.70*vec3(
        .40*softbox + .176*side + .029*shoulder + .056*meniscus);
    // Apply the highlight after body coverage. Shallow droplets and lens edges
    // retain a visible glint with gentler coverage attenuation at thin edges.
    gl_FragColor = vec4(body+specular*sqrt(contact),1.);
}
"""
