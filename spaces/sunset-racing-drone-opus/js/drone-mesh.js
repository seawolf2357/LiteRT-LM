// ═══════════════════════════════════════════════════════
//  DRONE MESH — compact quad drone: carbon-fibre X frame,
//  four arms, four props, center body with LED accent.
//  Returns a THREE.Group you drop into the scene.
// ═══════════════════════════════════════════════════════
import * as THREE from 'three';

export function createDroneMesh({ bodyColor = 0x2a2a30, ledColor = 0xff6a3d } = {}) {
  const group = new THREE.Group();
  group.name = 'drone';

  // ── Center body (flat cuboid) ──────────────────────────
  const bodyGeo = new THREE.BoxGeometry(1.2, 0.25, 0.9);
  const bodyMat = new THREE.MeshStandardMaterial({
    color: bodyColor,
    metalness: 0.55,
    roughness: 0.35,
    emissive: 0x101014,
  });
  const body = new THREE.Mesh(bodyGeo, bodyMat);
  body.castShadow = true;
  group.add(body);

  // Front LED strip (bright, unlit so it reads in any lighting)
  const ledGeo = new THREE.BoxGeometry(0.7, 0.05, 0.05);
  const ledMat = new THREE.MeshBasicMaterial({ color: ledColor });
  const led = new THREE.Mesh(ledGeo, ledMat);
  led.position.set(0, 0.13, -0.42);
  group.add(led);

  // Top cap (camera + battery hump)
  const capGeo = new THREE.BoxGeometry(0.55, 0.22, 0.45);
  const capMat = new THREE.MeshStandardMaterial({
    color: 0x1a1a1e, metalness: 0.3, roughness: 0.6,
  });
  const cap = new THREE.Mesh(capGeo, capMat);
  cap.position.y = 0.22;
  group.add(cap);

  // ── Arms + motors + props ──────────────────────────────
  const armMat = new THREE.MeshStandardMaterial({
    color: 0x111115, metalness: 0.2, roughness: 0.7,
  });
  const motorMat = new THREE.MeshStandardMaterial({
    color: 0x4a4a52, metalness: 0.8, roughness: 0.25,
  });
  const propMat = new THREE.MeshStandardMaterial({
    color: 0xdddde0,
    metalness: 0.1,
    roughness: 0.6,
    transparent: true,
    opacity: 0.55,
    side: THREE.DoubleSide,
  });

  // Four motor positions at the corners of an X.
  const R = 0.92;        // arm length from center
  const armLen = 1.05;
  const motorPositions = [
    [ R, 0.08,  R],
    [-R, 0.08,  R],
    [ R, 0.08, -R],
    [-R, 0.08, -R],
  ];

  const propellers = []; // we'll spin these every frame

  for (const [x, y, z] of motorPositions) {
    // Arm (thin cylinder rotated to face center)
    const armGeo = new THREE.CylinderGeometry(0.06, 0.06, armLen, 6);
    const arm = new THREE.Mesh(armGeo, armMat);
    arm.position.set(x * 0.5, y * 0.7, z * 0.5);
    arm.lookAt(new THREE.Vector3(x, y * 0.7, z));
    arm.rotateX(Math.PI / 2);
    group.add(arm);

    // Motor (short cylinder on arm tip)
    const motorGeo = new THREE.CylinderGeometry(0.17, 0.17, 0.18, 10);
    const motor = new THREE.Mesh(motorGeo, motorMat);
    motor.position.set(x, y + 0.12, z);
    group.add(motor);

    // Propeller disc (we spin this; it's a thin flat box pair
    // so it reads as a propeller even when not blurred).
    const propGroup = new THREE.Group();
    propGroup.position.set(x, y + 0.22, z);

    const blade1Geo = new THREE.BoxGeometry(1.0, 0.02, 0.08);
    const blade1 = new THREE.Mesh(blade1Geo, propMat);
    propGroup.add(blade1);

    const blade2 = blade1.clone();
    blade2.rotation.y = Math.PI / 2;
    propGroup.add(blade2);

    group.add(propGroup);
    propellers.push(propGroup);
  }

  /** Spin propellers based on phase accumulator from physics. */
  function spinProps(phase) {
    for (let i = 0; i < propellers.length; i++) {
      // Opposite pairs spin opposite directions (realistic quad).
      const dir = (i === 0 || i === 3) ? 1 : -1;
      propellers[i].rotation.y = phase * dir;
    }
  }

  return { group, spinProps };
}
